"""Bot Telegram.

Alur: kirim foto struk atau tulis transaksi -> bot menampilkan draft ->
pengguna menekan Simpan / Ubah / Batal. Tidak ada yang masuk laporan
sebelum dikonfirmasi.
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Account, Budget, Category, Transaction, utcnow
from app.services import ingest
from app.services.dates import format_dt
from app.services.merchant import remember_merchant
from app.services.money import extract_amount, format_idr, parse_amount
from app.services import ledger, wallet
from app.services.dates import current_period, now_local, to_utc, shift_period, month_bounds, period_label
from app.services.budget_alerts import check_and_send_alerts

logger = logging.getLogger(__name__)
router = Router()
bot_instance: Bot | None = None

# Media group queue: {chat_id: {group_id: [(message_id, bytes), ...]}}
_media_group_queue: dict[int, dict[str, list[tuple[int, bytes]]]] = {}
_media_group_timeout: dict[str, asyncio.Task] = {}

# Budget edit state: {chat_id: {"category_id": int}}
_budget_edit_state: dict[int, dict] = {}


async def _flush_media_group(chat_id: int, group_id: str) -> None:
    """Proses semua foto dari media group menjadi transaksi."""
    queue = _media_group_queue.get(chat_id, {})
    items = queue.pop(group_id, [])
    if not items:
        return

    async def _process_one(msg_id: int, img: bytes):
        status_msg = None
        try:
            with SessionLocal() as db:
                transaction, _data = await ingest.draft_from_photo(
                    db,
                    img,
                    chat_id=chat_id,
                    message_id=msg_id,
                    update_id=msg_id,
                )
                if transaction:
                    text, keyboard = _render(db, transaction)
                    status_msg = await bot.send_message(
                        chat_id,
                        text,
                        reply_markup=keyboard,
                        reply_to_message_id=msg_id,
                    )
        except Exception as exc:
            logger.warning("Media group processing error: %s", exc)
            if status_msg:
                await bot.edit_message_text(
                    "Gagal memproses foto. Coba lagi.",
                    chat_id,
                    status_msg.message_id,
                )

    tasks = [_process_one(mid, img) for mid, img in items]
    await asyncio.gather(*tasks)


HELP_TEXT = (
    "╔════════════════════════╗\n"
    "║  <b>📚 PANDUAN BOT</b>\n"
    "╠════════════════════════╣\n\n"
    "<b>💰 CATAT TRANSAKSI</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "• <code>makan 50rb warteg</code>\n"
    "• <code>gaji 5jt bonus</code>\n"
    "• <code>bensin 100k shell</code>\n\n"
    "<b>📊 LAPORAN</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "• /saldo - Saldo semua akun\n"
    "• /budget - Monitoring budget\n"
    "• /ringkasan - Kondisi keuangan\n"
    "• /pengeluaran - Total expense\n"
    "• /pemasukan - Total income\n"
    "• /transaksi - Transaksi terakhir\n\n"
    "<b>📁 KELOLA KATEGORI</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "• <code>tambah kategori olahraga</code>\n"
    "• <code>ubah kategori makan jadi makanan</code>\n"
    "• <code>hapus kategori lain-lain</code>\n\n"
    "<b>💳 ATUR BUDGET</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "• <code>budget makanan 2jt</code>\n"
    "• <code>budget transport 500rb</code>\n\n"
    "<b>💡 TIPS</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "Format: [kategori] [nominal] [keterangan]\n"
    "Nominal: 50rb, 2jt, 100k, 1.5jt\n"
    "Otomatis expense, pakai 'gaji/bonus' untuk income\n\n"
    "╚════════════════════════╝"
)


class EditAmount(StatesGroup):
    waiting = State()


def _allowed(chat_id: int | None) -> bool:
    """Hanya satu chat yang boleh memakai bot ini."""
    allowed_id = settings.telegram_chat_id
    return allowed_id is not None and chat_id == allowed_id


def _keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Simpan", callback_data=f"tx:ok:{transaction_id}"),
                InlineKeyboardButton(text="Ubah nominal", callback_data=f"tx:amt:{transaction_id}"),
            ],
            [
                InlineKeyboardButton(text="Ubah kategori", callback_data=f"tx:cat:{transaction_id}"),
                InlineKeyboardButton(text="Batal", callback_data=f"tx:no:{transaction_id}"),
            ],
        ]
    )


def _category_keyboard(transaction_id: int, categories: list[Category]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    last_kind = None

    for category in categories:
        if category.kind != last_kind:
            if current:
                rows.append(current)
                current = []
            label = "Pemasukan" if category.kind == "income" else "Pengeluaran"
            rows.append([InlineKeyboardButton(text=f"— {label} —", callback_data="tx:noop")])
            last_kind = category.kind
        current.append(
            InlineKeyboardButton(
                text=category.name,
                callback_data=f"tx:setcat:{transaction_id}:{category.id}",
            )
        )
        if len(current) == 2:
            rows.append(current)
            current = []

    if current:
        rows.append(current)

    rows.append([InlineKeyboardButton(text="Kembali", callback_data=f"tx:back:{transaction_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "tx:noop")
async def callback_category_header(callback: CallbackQuery) -> None:
    await callback.answer()


def _render(db, transaction: Transaction) -> tuple[str, InlineKeyboardMarkup]:
    category = db.get(Category, transaction.category_id) if transaction.category_id else None
    account = db.get(Account, transaction.account_id) if transaction.account_id else None

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "  <b>Perlu konfirmasi</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    
    if transaction.merchant:
        lines.append(f"🏪  {html.escape(transaction.merchant)}")
    
    lines.append(f"💰  <code>{format_idr(transaction.amount)}</code>")
    lines.append(f"📁  {html.escape(category.name) if category else '⚠️ Belum dipilih'}")
    lines.append(f"👛  {html.escape(account.name) if account else '⚠️ Belum dipilih'}")
    lines.append(f"🕐  {format_dt(transaction.occurred_at)}")

    if transaction.confidence is not None:
        conf_pct = round(transaction.confidence * 100)
        conf_emoji = "✅" if conf_pct >= 80 else "⚠️" if conf_pct >= 60 else "❌"
        lines.append(f"{conf_emoji}  Keyakinan: {conf_pct}%")

    if transaction.amount <= 0:
        lines.append("")
        lines.append("⚠️ <i>Nominal belum terbaca, mohon ubah manual</i>")

    lines.append("")
    lines.append("─" * 30)
    
    return "\n".join(lines), _keyboard(transaction.id)


def _render_budget_preview(db: Session, category_id: int, amount: int) -> tuple[str, InlineKeyboardMarkup]:
    """Render budget preview dengan style minimalis."""
    from app.models import Category, Budget
    from sqlalchemy import select
    
    category = db.get(Category, category_id)
    period = current_period()
    
    existing = db.scalar(
        select(Budget).where(
            Budget.category_id == category_id,
            Budget.period == period
        )
    )
    
    action = "Update" if existing else "Buat"
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"  <b>{action} Budget</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    
    lines.append(f"📁  {html.escape(category.name) if category else '-'}")
    lines.append(f"💰  <code>{format_idr(amount)}</code>")
    lines.append(f"📅  {period_label(period)}")
    
    if existing:
        lines.append("")
        lines.append(f"<i>Sebelumnya: {format_idr(existing.amount)}</i>")
    
    # Keyboard dengan opsi edit
    buttons = [
        [
            InlineKeyboardButton(text="📁 Kategori", callback_data=f"budget_edit_cat:{category_id}:{amount}"),
            InlineKeyboardButton(text="💰 Nominal", callback_data=f"budget_edit_amt:{category_id}")
        ],
        [
            InlineKeyboardButton(text="✅ Konfirmasi", callback_data=f"budget_confirm:{category_id}:{amount}"),
            InlineKeyboardButton(text="❌ Batal", callback_data="budget_cancel")
        ]
    ]
    
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    await message.answer(HELP_TEXT)


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    await message.answer(HELP_TEXT)


def _financial_summary() -> str:
    with SessionLocal() as db:
        period = current_period()
        data = ledger.analytics(db, period)
        balances = ledger.account_balances(db)
        budgets = ledger.budget_progress(db, period)
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "  <b>💼 Ringkasan Keuangan</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    
    # Saldo Section
    total_saldo = sum(item['balance'] for item in balances)
    lines.append("┌─ 💰 <b>SALDO TOTAL</b>")
    lines.append(f"│  <code>{format_idr(total_saldo)}</code>")
    for acc in balances[:3]:
        lines.append(f"│  • {acc['name']}: {format_idr(acc['balance'])}")
    if len(balances) > 3:
        lines.append(f"│  ... +{len(balances) - 3} dompet lainnya")
    lines.append("└────────────────────────────")
    lines.append("")
    
    # Cashflow Section
    lines.append(f"┌─ 📊 <b>CASHFLOW {data['label'].upper()}</b>")
    lines.append(f"│  📈 Pemasukan: <code>{format_idr(data['income'])}</code>")
    lines.append(f"│  📉 Pengeluaran: <code>{format_idr(data['expense'])}</code>")
    
    net_emoji = "✅" if data['net'] >= 0 else "⚠️"
    lines.append(f"│  {net_emoji} Net: <code>{format_idr(data['net'])}</code>")
    lines.append(f"│  📅 Rata-rata/hari: {format_idr(data['daily_average'])}")
    lines.append("└────────────────────────────")
    
    # Top Category
    if data["top_category"]:
        lines.append("")
        lines.append("┌─ 🔥 <b>KATEGORI TERBESAR</b>")
        lines.append(f"│  {data['top_category']['name']}")
        lines.append(f"│  {format_idr(data['top_category']['total'])}")
        lines.append("└────────────────────────────")
    
    # Budget Section
    if budgets:
        lines.append("")
        total_budget = sum(x['amount'] for x in budgets)
        total_spent = sum(x['spent'] for x in budgets)
        remaining = total_budget - total_spent
        progress_pct = round((total_spent / total_budget * 100) if total_budget > 0 else 0)
        
        lines.append("┌─ 🎯 <b>BUDGET BULAN INI</b>")
        lines.append(f"│  Total: <code>{format_idr(total_budget)}</code>")
        lines.append(f"│  Terpakai: <code>{format_idr(total_spent)}</code> ({progress_pct}%)")
        
        remaining_emoji = "💚" if progress_pct < 70 else "⚡" if progress_pct < 90 else "🔴"
        lines.append(f"│  {remaining_emoji} Sisa: <code>{format_idr(remaining)}</code>")
        lines.append("│")
        
        over = [item for item in budgets if item["over"]]
        if over:
            lines.append("│  ⚠️ <b>OVER BUDGET:</b>")
            for item in over[:3]:
                lines.append(f"│  🔴 {item['name']}: {item['pct']}%")
        else:
            for item in budgets[:3]:
                emoji = "💚" if item['pct'] < 70 else "⚡" if item['pct'] < 90 else "🔴"
                lines.append(f"│  {emoji} {item['name']}: {item['pct']}%")
        
        if len(budgets) > 3:
            lines.append(f"│  ... +{len(budgets) - 3} kategori lainnya")
        lines.append("└────────────────────────────")
    else:
        lines.append("")
        lines.append("┌─ 🎯 <b>BUDGET</b>")
        lines.append("│  ⚠️ Belum ada budget bulan ini")
        lines.append("│  Ketik: <code>budget [kategori] [jumlah]</code>")
        lines.append("└────────────────────────────")
    
    return "\n".join(lines)


async def _handle_add_category(db: Session, text: str, message: Message) -> None:
    """Tambah kategori baru dari natural language."""
    from app.models import Category
    from sqlalchemy import select
    
    text_lower = text.lower()
    for keyword in ["tambah kategori", "kategori baru", "buat kategori"]:
        text_lower = text_lower.replace(keyword, "")
    
    kind = "income" if any(w in text_lower for w in ["income", "pemasukan"]) else "expense"
    for w in ["income", "pemasukan", "pengeluaran", "expense"]:
        text_lower = text_lower.replace(w, "")
    
    name = text_lower.strip().title()
    
    if not name or len(name) < 2:
        await message.reply("❌ Nama kategori terlalu pendek")
        return
    
    existing = db.scalar(select(Category).where(Category.name == name))
    if existing:
        await message.reply(f"❌ Kategori <b>{name}</b> sudah ada", parse_mode="HTML")
        return
    
    # Konfirmasi dengan pilihan jenis
    buttons = [
        [
            InlineKeyboardButton(text="📉 Pengeluaran", callback_data=f"cat_add_type:{name}:expense"),
            InlineKeyboardButton(text="📈 Pemasukan", callback_data=f"cat_add_type:{name}:income")
        ],
        [
            InlineKeyboardButton(text="❌ Batal", callback_data="cat_cancel")
        ]
    ]
    
    kind_text = "📈 Pemasukan" if kind == "income" else "📉 Pengeluaran"
    
    await message.reply(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>Tambah Kategori</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📁  <b>{name}</b>\n\n"
        f"Terdeteksi sebagai: {kind_text}\n\n"
        "Pilih jenis kategori:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


async def _handle_delete_category(db: Session, text: str, message: Message) -> None:
    """Hapus kategori dari natural language."""
    from app.models import Category, Transaction
    from sqlalchemy import select, func
    
    text_lower = text.lower()
    for keyword in ["hapus kategori", "delete kategori"]:
        text_lower = text_lower.replace(keyword, "")
    
    name = text_lower.strip()
    
    if not name:
        await message.reply("❌ Nama kategori tidak ditemukan")
        return
    
    categories = db.scalars(select(Category)).all()
    category = None
    for cat in categories:
        if cat.name.lower() == name.lower():
            category = cat
            break
    
    if not category:
        await message.reply(f"❌ Kategori <b>{name}</b> tidak ditemukan", parse_mode="HTML")
        return
    
    usage_count = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.category_id == category.id,
            Transaction.deleted_at.is_(None)
        )
    )
    
    if usage_count > 0:
        await message.reply(
            f"❌ Tidak bisa hapus kategori <b>{category.name}</b>\n\n"
            f"Digunakan di {usage_count} transaksi.\n"
            f"Hapus atau ubah transaksi dulu.",
            parse_mode="HTML"
        )
        return
    
    # Konfirmasi hapus
    buttons = [
        [
            InlineKeyboardButton(text="✅ Ya, Hapus", callback_data=f"cat_del_confirm:{category.id}"),
            InlineKeyboardButton(text="❌ Batal", callback_data="cat_cancel")
        ]
    ]
    
    await message.reply(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>⚠️ Konfirmasi Hapus</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📁  {category.name}\n\n"
        "Yakin hapus kategori ini?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


async def _handle_rename_category(db: Session, text: str, message: Message) -> None:
    """Ubah nama kategori dari natural language."""
    from app.models import Category
    from sqlalchemy import select
    
    text_lower = text.lower()
    
    parts = text_lower.split("jadi")
    if len(parts) != 2:
        await message.reply("❌ Format: <code>ubah kategori [lama] jadi [baru]</code>", parse_mode="HTML")
        return
    
    old_name = parts[0].replace("ubah kategori", "").strip()
    new_name = parts[1].strip().title()
    
    if not old_name or not new_name:
        await message.reply("❌ Nama kategori tidak lengkap")
        return
    
    categories = db.scalars(select(Category)).all()
    category = None
    for cat in categories:
        if cat.name.lower() == old_name.lower():
            category = cat
            break
    
    if not category:
        await message.reply(f"❌ Kategori <b>{old_name}</b> tidak ditemukan", parse_mode="HTML")
        return
    
    existing = db.scalar(select(Category).where(Category.name == new_name))
    if existing and existing.id != category.id:
        await message.reply(f"❌ Kategori <b>{new_name}</b> sudah ada", parse_mode="HTML")
        return
    
    # Konfirmasi rename
    buttons = [
        [
            InlineKeyboardButton(text="✅ Ya, Ubah", callback_data=f"cat_rename_confirm:{category.id}:{new_name}"),
            InlineKeyboardButton(text="❌ Batal", callback_data="cat_cancel")
        ]
    ]
    
    await message.reply(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>Konfirmasi Ubah Nama</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📁  {category.name} → {new_name}\n\n"
        "Lanjutkan?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


async def _import_csv(db: Session, content: str, message: Message) -> str:
    """Import CSV lewat service bersama (dompet otomatis dibuat & disinkronkan)."""
    from app.services import importer

    result = importer.import_csv(db, content, source="telegram")

    if result.imported == 0:
        detail = result.messages[0] if result.messages else "File tidak bisa dibaca"
        return f"❌ Import gagal: {detail}"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "  <b>📥 Import Selesai</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"✅  {result.imported} transaksi berhasil",
    ]

    if result.accounts_created:
        names = ", ".join(result.accounts_created[:5])
        extra = "" if len(result.accounts_created) <= 5 else " ..."
        lines.append(f"👛  Dompet dibuat: {names}{extra}")

    if result.errors:
        lines.append(f"⚠️  {result.errors} baris error")
        for note in result.messages[:5]:
            lines.append(f"• {note}")

    if result.wallets:
        lines.append("")
        lines.append("<i>Saldo dompet (dari transaksi):</i>")
        for wallet_info in result.wallets[:5]:
            lines.append(f"• {wallet_info['name']}: {format_idr(wallet_info['balance'])}")

    return "\n".join(lines)


async def _handle_info_query(db: Session, question: str) -> str | None:
    """Handle query info natural language tentang status data."""
    from app.models import Category, Account, Transaction, Budget
    from sqlalchemy import select, func
    from app.services.dates import current_period, period_label
    
    period = current_period()
    
    # Query count kategori
    if any(w in question for w in ["berapa kategori", "jumlah kategori", "total kategori"]):
        expense_count = db.scalar(select(func.count(Category.id)).where(Category.kind == "expense"))
        income_count = db.scalar(select(func.count(Category.id)).where(Category.kind == "income"))
        total = expense_count + income_count
        
        return (
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  <b>📊 Info Kategori</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁  Total: {total} kategori\n"
            f"📉  Pengeluaran: {expense_count}\n"
            f"📈  Pemasukan: {income_count}"
        )
    
    # List kategori
    if any(w in question for w in ["kategori apa", "daftar kategori", "list kategori"]):
        categories = db.scalars(select(Category).order_by(Category.kind, Category.name)).all()
        if not categories:
            return "❌ Belum ada kategori"
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>📁 Daftar Kategori</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        expense_cats = [c for c in categories if c.kind == "expense"]
        income_cats = [c for c in categories if c.kind == "income"]
        
        if expense_cats:
            lines.append("<b>📉 Pengeluaran</b>")
            for cat in expense_cats:
                lines.append(f"  • {cat.name}")
            lines.append("")
        
        if income_cats:
            lines.append("<b>📈 Pemasukan</b>")
            for cat in income_cats:
                lines.append(f"  • {cat.name}")
        
        return "\n".join(lines)
    
    # Query akun/dompet
    if any(w in question for w in ["berapa dompet", "jumlah akun", "dompet apa", "akun apa", "list dompet", "daftar akun"]):
        accounts = db.scalars(select(Account).where(Account.archived == False)).all()
        if not accounts:
            return "❌ Belum ada akun"
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>👛 Daftar Akun</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        from app.services.ledger import account_balances
        balances = account_balances(db)
        balance_map = {b['id']: b['balance'] for b in balances}
        
        for acc in accounts:
            balance = balance_map.get(acc.id, 0)
            lines.append(f"  • {acc.name}: {format_idr(balance)}")
        
        return "\n".join(lines)
    
    # Query transaksi count dengan periode
    if any(w in question for w in ["berapa transaksi", "jumlah transaksi", "total transaksi"]):
        # Detect periode
        target_period = period
        
        if any(w in question for w in ["bulan ini", "sekarang", "current"]):
            target_period = period
        elif any(w in question for w in ["bulan lalu", "kemarin"]):
            from datetime import datetime
            now = datetime.now()
            prev_month = now.month - 1 if now.month > 1 else 12
            prev_year = now.year if now.month > 1 else now.year - 1
            target_period = f"{prev_year}-{prev_month:02d}"
        elif any(w in question for w in ["semua", "total", "keseluruhan"]):
            target_period = "all"
        
        if target_period == "all":
            count = db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.deleted_at.is_(None),
                    Transaction.status == "confirmed"
                )
            )
            
            return (
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  <b>📊 Info Transaksi</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📝  {count} transaksi total"
            )
        else:
            count = db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.deleted_at.is_(None),
                    Transaction.status == "confirmed",
                    func.strftime("%Y-%m", Transaction.occurred_at) == target_period
                )
            )
            
            return (
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  <b>📊 Info Transaksi</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📝  {count} transaksi\n"
                f"📅  {period_label(target_period)}"
            )
    
    # Query budget dengan periode
    if any(w in question for w in ["berapa budget", "budget apa", "daftar budget", "list budget"]):
        target_period = period
        
        if any(w in question for w in ["bulan lalu", "kemarin"]):
            from datetime import datetime
            now = datetime.now()
            prev_month = now.month - 1 if now.month > 1 else 12
            prev_year = now.year if now.month > 1 else now.year - 1
            target_period = f"{prev_year}-{prev_month:02d}"
        
        budgets = db.scalars(
            select(Budget).where(Budget.period == target_period)
        ).all()
        
        if not budgets:
            return f"❌ Belum ada budget untuk {period_label(target_period)}"
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            f"  <b>💼 Budget {period_label(target_period)}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        total_budget = sum(b.amount for b in budgets)
        lines.append(f"💰  Total: {format_idr(total_budget)}")
        lines.append("")
        
        for b in budgets:
            cat = db.get(Category, b.category_id)
            if cat:
                lines.append(f"  • {cat.name}: {format_idr(b.amount)}")
        
        return "\n".join(lines)
    
    # Query pengeluaran per kategori
    if any(w in question for w in ["pengeluaran per kategori", "spending per kategori", "breakdown kategori"]):
        target_period = period
        
        expenses = db.execute(
            select(
                Category.name,
                func.sum(Transaction.amount).label('total')
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.deleted_at.is_(None),
                Transaction.status == "confirmed",
                Transaction.kind == "expense",
                func.strftime("%Y-%m", Transaction.occurred_at) == target_period
            )
            .group_by(Category.id, Category.name)
            .order_by(func.sum(Transaction.amount).desc())
        ).all()
        
        if not expenses:
            return f"❌ Belum ada pengeluaran di {period_label(target_period)}"
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            f"  <b>📊 Pengeluaran {period_label(target_period)}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        total = sum(e.total for e in expenses)
        lines.append(f"💰  Total: {format_idr(total)}")
        lines.append("")
        
        for e in expenses[:10]:
            pct = int(e.total / total * 100) if total > 0 else 0
            lines.append(f"  • {e.name}: {format_idr(e.total)} ({pct}%)")
        
        if len(expenses) > 10:
            lines.append(f"  ... +{len(expenses) - 10} kategori lainnya")
        
        return "\n".join(lines)
    
    # Query merchant terbanyak
    if any(w in question for w in ["merchant terbanyak", "toko favorit", "merchant sering"]):
        target_period = period
        
        merchants = db.execute(
            select(
                Transaction.merchant,
                func.count(Transaction.id).label('count'),
                func.sum(Transaction.amount).label('total')
            )
            .where(
                Transaction.deleted_at.is_(None),
                Transaction.status == "confirmed",
                Transaction.merchant.isnot(None),
                func.strftime("%Y-%m", Transaction.occurred_at) == target_period
            )
            .group_by(Transaction.merchant)
            .order_by(func.count(Transaction.id).desc())
            .limit(10)
        ).all()
        
        if not merchants:
            return f"❌ Belum ada data merchant di {period_label(target_period)}"
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            f"  <b>🏪 Merchant Terbanyak</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅  {period_label(target_period)}",
            ""
        ]
        
        for m in merchants:
            lines.append(f"  • {m.merchant}: {m.count}x ({format_idr(m.total)})")
        
        return "\n".join(lines)
    
    # Query transaksi/pengeluaran untuk merchant tertentu, mis. "pengeluaran di indomaret"
    if any(w in question for w in ("pengeluaran", "belanja", "transaksi", "riwayat", "berapa", "total")):
        known_merchants = db.scalars(
            select(Transaction.merchant)
            .where(Transaction.merchant.isnot(None), Transaction.deleted_at.is_(None))
            .distinct()
        ).all()
        mentioned = [m for m in known_merchants if m and m.lower() in question]

        if mentioned:
            # Periode: minggu ini kalau disebut, selain itu bulan berjalan.
            if "minggu" in question:
                today = now_local().date()
                start_day = today - timedelta(days=today.weekday())
                start = to_utc(
                    datetime.combine(start_day, datetime.min.time(), tzinfo=now_local().tzinfo)
                )
                end = to_utc(now_local() + timedelta(seconds=1))
                label = "Minggu ini"
            else:
                start, end = month_bounds(period)
                label = period_label(period)

            rows = db.execute(
                select(
                    Transaction.merchant,
                    func.count(Transaction.id),
                    func.coalesce(func.sum(Transaction.amount), 0),
                )
                .where(
                    Transaction.deleted_at.is_(None),
                    Transaction.status == "confirmed",
                    Transaction.kind == "expense",
                    Transaction.merchant.in_(mentioned),
                    Transaction.occurred_at >= start,
                    Transaction.occurred_at < end,
                )
                .group_by(Transaction.merchant)
                .order_by(func.sum(Transaction.amount).desc())
            ).all()

            if not rows:
                return (
                    f"❌ Belum ada pengeluaran di <b>{', '.join(mentioned)}</b> "
                    f"untuk {label}"
                )

            lines = [
                "━━━━━━━━━━━━━━━━━━━━━━━",
                "  <b>🏪 Pengeluaran Merchant</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━",
                f"📅  {label}",
                "",
            ]
            total = sum(int(row[2] or 0) for row in rows)
            for merchant, count, amount in rows:
                lines.append(
                    f"  • <b>{merchant}</b>: {format_idr(int(amount or 0))} "
                    f"({count} transaksi)"
                )
            lines.append("")
            lines.append(f"<b>Total:</b> <code>{format_idr(total)}</code>")
            return "\n".join(lines)

    # Minta bantuan mengatur budget tanpa menyebut nominal.
    if any(w in question for w in ("atur budget", "setting budget", "kelola budget", "cara budget")):
        budgets = db.scalars(select(Budget).where(Budget.period == period)).all()
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>💼 Atur Budget</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        if budgets:
            lines.append(f"Budget {period_label(period)} saat ini:")
            for b in budgets:
                cat = db.get(Category, b.category_id)
                if cat:
                    lines.append(f"  • {cat.name}: {format_idr(b.amount)}")
            lines.append("")
        lines.append("Ubah dengan format:")
        lines.append("<code>budget [kategori] [jumlah]</code>")
        lines.append("Contoh: <code>budget makanan 2jt</code>")
        return "\n".join(lines)

    return None


async def _handle_budget_set(db: Session, text: str, amount: int, message: Message) -> None:
    """Parse dan set budget dari text natural, konfirmasi dulu sebelum save."""
    from app.models import Category, Budget
    from sqlalchemy import select
    
    text_lower = text.lower()
    
    # Extract category name
    for keyword in ["budget", "anggaran", "atur", "set"]:
        text_lower = text_lower.replace(keyword, "")
    
    for num_word in ["rb", "ribu", "jt", "juta", "k", "m", "rp", "."]:
        text_lower = text_lower.replace(num_word, "")
    
    import re
    text_lower = re.sub(r'\d+', '', text_lower).strip()
    category_query = text_lower.strip()
    
    # Find matching categories
    categories = db.scalars(
        select(Category).where(Category.kind == "expense")
    ).all()
    
    matches = []
    for cat in categories:
        if category_query and (category_query in cat.name.lower() or cat.name.lower() in category_query):
            matches.append(cat)
    
    if not matches:
        available = "\n".join([f"• {c.name}" for c in categories[:10]])
        await message.reply(f"❌ Kategori tidak ditemukan. Coba salah satu:\n{available}")
        return
    
    # Jika 1 match, langsung render preview. Jika banyak, kasih pilihan
    category = matches[0]
    
    # Render budget preview dengan opsi edit
    text_preview, keyboard = _render_budget_preview(db, category.id, amount)
    await message.reply(text_preview, reply_markup=keyboard, parse_mode="HTML")


def _question_period(text: str) -> tuple[datetime, datetime, str] | None:
    """Parse hari/minggu/bulan dari pertanyaan natural-language."""
    now = now_local()
    today = now.date()
    lowered = text.lower().replace("mingguini", "minggu ini").replace("bulanini", "bulan ini")
    if "hari ini" in lowered or "hari" in lowered:
        start = datetime.combine(today, datetime.min.time(), tzinfo=now.tzinfo)
        return to_utc(start), to_utc(now + timedelta(seconds=1)), "Hari ini"
    if "kemarin" in lowered:
        day = today - timedelta(days=1)
        start = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo)
        return to_utc(start), to_utc(start + timedelta(days=1)), "Kemarin"
    if "minggu lalu" in lowered:
        start_day = today - timedelta(days=today.weekday() + 7)
        start = datetime.combine(start_day, datetime.min.time(), tzinfo=now.tzinfo)
        return to_utc(start), to_utc(start + timedelta(days=7)), "Minggu lalu"
    if "minggu" in lowered:
        start_day = today - timedelta(days=today.weekday())
        start = datetime.combine(start_day, datetime.min.time(), tzinfo=now.tzinfo)
        return to_utc(start), to_utc(now + timedelta(seconds=1)), "Minggu ini"

    month_names = {"januari": 1, "jan": 1, "februari": 2, "feb": 2, "maret": 3, "mar": 3, "april": 4, "apr": 4, "mei": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "agustus": 8, "agu": 8, "september": 9, "sep": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11, "desember": 12, "des": 12}
    match = re.search(r"\b(" + "|".join(month_names) + r")\s*(20\d{2})?\b", lowered)
    if match:
        month = month_names[match.group(1)]
        year = int(match.group(2) or now.year)
        period = f"{year:04d}-{month:02d}"
    elif "bulan lalu" in lowered:
        period = shift_period(current_period(), -1)
    elif "bulan" in lowered:
        period = current_period()
    else:
        return None
    start, end = month_bounds(period)
    return start, end, f"Bulan {period[5:7]}/{period[:4]}"


def _answer_finance_question(text: str) -> str | None:
    lower = text.lower()
    
    # Sisa saldo total
    if any(x in lower for x in ("sisa saldo", "total saldo", "saldo saya", "berapa saldo")):
        with SessionLocal() as db:
            balances = ledger.account_balances(db)
            total = sum(item['balance'] for item in balances)
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>💰 Sisa Saldo</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"<b>TOTAL</b>: <code>{format_idr(total)}</code>",
            "",
            "┌─ <b>DETAIL PER DOMPET</b>"
        ]
        
        for x in balances:
            emoji = "💳" if x['kind'] == 'bank' else "📱" if x['kind'] == 'ewallet' else "💵"
            lines.append(f"│ {emoji} {x['name']}")
            lines.append(f"│   <code>{format_idr(x['balance'])}</code>")
        
        lines.append("└───────────────────────────")
        return "\n".join(lines)
    
    # Sisa budget/anggaran
    if any(x in lower for x in ("sisa budget", "sisa anggaran", "berapa budget", "berapa anggaran")):
        with SessionLocal() as db:
            items = ledger.budget_progress(db, current_period())
        
        if not items:
            return "⚠️ Belum ada budget bulan ini.\n\nKetik: <code>budget [kategori] [jumlah]</code>"
        
        # Extract category query
        query_text = lower
        for keyword in ["sisa", "budget", "anggaran", "berapa", "kategori"]:
            query_text = query_text.replace(keyword, "")
        query_text = query_text.strip()
        
        # If specific category mentioned
        if query_text:
            matches = [x for x in items if query_text in x['name'].lower()]
            if matches:
                lines = [
                    "━━━━━━━━━━━━━━━━━━━━━━━",
                    "  <b>🎯 Budget Detail</b>",
                    "━━━━━━━━━━━━━━━━━━━━━━━",
                    ""
                ]
                for x in matches:
                    status_emoji = "🔴" if x['over'] else "💚" if x['pct'] < 70 else "⚡"
                    status_text = "OVER BUDGET!" if x['over'] else "On Track"
                    
                    lines.append(f"┌─ <b>{x['name']}</b> {status_emoji}")
                    lines.append(f"│  Budget: <code>{format_idr(x['amount'])}</code>")
                    lines.append(f"│  Terpakai: <code>{format_idr(x['spent'])}</code>")
                    lines.append(f"│  Progress: {x['pct']}%")
                    lines.append(f"│  <b>Sisa: {format_idr(x['remaining'])}</b>")
                    lines.append(f"│  Status: {status_text}")
                    lines.append("└───────────────────────────")
                
                return "\n".join(lines)
        
        # Show all
        total_budget = sum(x['amount'] for x in items)
        total_spent = sum(x['spent'] for x in items)
        total_remaining = sum(x['remaining'] for x in items)
        progress_pct = round((total_spent / total_budget * 100) if total_budget > 0 else 0)
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>🎯 Sisa Budget Bulan Ini</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"Total Budget: <code>{format_idr(total_budget)}</code>",
            f"Total Terpakai: <code>{format_idr(total_spent)}</code> ({progress_pct}%)",
            f"<b>Total Sisa: {format_idr(total_remaining)}</b>",
            "",
            "┌─ <b>DETAIL PER KATEGORI</b>"
        ]
        
        for x in items:
            emoji = "🔴" if x['over'] else "💚" if x['pct'] < 70 else "⚡"
            sisa_pct = max(0, 100 - x['pct'])
            lines.append(f"│ {emoji} {x['name']}")
            lines.append(f"│   Sisa: <code>{format_idr(x['remaining'])}</code> ({sisa_pct}%)")
        
        lines.append("└─────────────────────────────")
        return "\n".join(lines)
    
    # Query spesifik per kategori, mis. "berapa untuk makanan minggu ini".
    # Cari nama kategori yang disebut user (case-insensitive).
    with SessionLocal() as db:
        expense_categories = db.scalars(select(Category).where(Category.kind == "expense")).all()
    mentioned = [c for c in expense_categories if c.name.lower() in lower]

    # Date range queries
    parsed = _question_period(text)
    if not parsed:
        if not mentioned:
            return None
        # Tidak ada kata periode, tapi user menyebut kategori: pakai bulan berjalan.
        period = current_period()
        start, end = month_bounds(period)
        label = period_label(period)
    else:
        start, end, label = parsed

    if mentioned:
        from sqlalchemy import func

        category_ids = [c.id for c in mentioned]
        with SessionLocal() as db:
            rows = db.execute(
                select(
                    Category.name,
                    func.count(Transaction.id),
                    func.coalesce(func.sum(Transaction.amount), 0),
                )
                .join(Transaction, Transaction.category_id == Category.id)
                .where(
                    Transaction.deleted_at.is_(None),
                    Transaction.status == "confirmed",
                    Transaction.kind == "expense",
                    Transaction.occurred_at >= start,
                    Transaction.occurred_at < end,
                    Category.id.in_(category_ids),
                )
                .group_by(Category.id, Category.name)
                .order_by(func.sum(Transaction.amount).desc())
            ).all()

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>📉 Pengeluaran per Kategori</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"<b>Periode:</b> {label}",
            "",
        ]

        if not rows:
            lines.append(f"Belum ada pengeluaran untuk <b>{', '.join(c.name for c in mentioned)}</b>.")
            return "\n".join(lines)

        total = sum(int(row[2] or 0) for row in rows)
        for name, count, amount in rows:
            lines.append(f"• <b>{name}</b>: <code>{format_idr(int(amount or 0))}</code> ({count} transaksi)")
        lines.append("")
        lines.append(f"<b>Total:</b> <code>{format_idr(total)}</code>")
        return "\n".join(lines)

    with SessionLocal() as db:
        data = ledger.range_summary(db, start, end)
    
    wants_income = any(x in lower for x in ("pemasukan", "pendapatan", "uang masuk", "income"))
    wants_expense = any(x in lower for x in ("pengeluaran", "spending", "belanja", "uang keluar", "expense"))
    
    if wants_income and not wants_expense:
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>📈 Pemasukan</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"<b>Periode:</b> {label}",
            "",
            f"<b>Total:</b> <code>{format_idr(data['income'])}</code>",
            f"Jumlah transaksi: {data['income_count']}"
        ]
        return "\n".join(lines)
    
    if wants_expense and not wants_income:
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>📉 Pengeluaran</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"<b>Periode:</b> {label}",
            "",
            f"<b>Total:</b> <code>{format_idr(data['expense'])}</code>",
            f"Jumlah transaksi: {data['expense_count']}"
        ]
        return "\n".join(lines)
    
    # Summary
    net_emoji = "✅" if data['net'] >= 0 else "⚠️"
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "  <b>📊 Kondisi Keuangan</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"<b>Periode:</b> {label}",
        "",
        f"📈 Pemasukan: <code>{format_idr(data['income'])}</code>",
        f"   ({data['income_count']} transaksi)",
        "",
        f"📉 Pengeluaran: <code>{format_idr(data['expense'])}</code>",
        f"   ({data['expense_count']} transaksi)",
        "",
        f"{net_emoji} <b>Cashflow: {format_idr(data['net'])}</b>"
    ]
    
    return "\n".join(lines)


@router.message(Command("ringkasan", "status"))
async def handle_summary(message: Message) -> None:
    if _allowed(message.chat.id):
        await message.answer(_financial_summary())


@router.message(Command("saldo"))
async def handle_balance(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    with SessionLocal() as db:
        balances = ledger.account_balances(db)
    
    total = sum(x['balance'] for x in balances)
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "  <b>💰 Saldo Dompet</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"<b>TOTAL</b>: <code>{format_idr(total)}</code>",
        "",
        "┌─ <b>DETAIL</b>"
    ]
    
    for x in balances:
        emoji = "💳" if x['kind'] == 'bank' else "📱" if x['kind'] == 'ewallet' else "💵"
        archived = " 📦" if x.get('archived') else ""
        lines.append(f"│ {emoji} {x['name']}{archived}")
        lines.append(f"│   <code>{format_idr(x['balance'])}</code>")
    
    lines.append("└───────────────────────────")
    
    await message.answer("\n".join(lines))


@router.message(Command("budget"))
async def handle_budget(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    
    # Extract category query from command args
    query = message.text.strip().split(maxsplit=1)
    category_query = query[1].lower() if len(query) > 1 else None
    
    with SessionLocal() as db:
        period = current_period()
        items = ledger.budget_progress(db, period)
    
    if not items:
        await message.answer(
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  <b>⚠️ Belum Ada Budget</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ketik: <code>budget [kategori] [jumlah]</code>\n\n"
            "<b>Contoh:</b>\n"
            "• <code>budget makanan 2jt</code>\n"
            "• <code>budget transport 500rb</code>"
        )
        return
    
    # Filter by category if specified
    if category_query:
        matches = [x for x in items if category_query in x['name'].lower()]
        if not matches:
            await message.answer(
                f"❌ Kategori '<code>{category_query}</code>' tidak ditemukan.\n\n"
                "<b>Kategori tersedia:</b>\n" + 
                "\n".join(f"• {x['name']}" for x in items)
            )
            return
        
        # Show detailed info for matched categories
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>🎯 Budget Detail</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        for x in matches:
            status_emoji = "🔴" if x['over'] else "💚" if x['pct'] < 70 else "⚡"
            status_text = "OVER BUDGET!" if x['over'] else "On Track"
            
            lines.append(f"┌─ <b>{x['name']}</b> {status_emoji}")
            lines.append(f"│  Budget: <code>{format_idr(x['amount'])}</code>")
            lines.append(f"│  Terpakai: <code>{format_idr(x['spent'])}</code>")
            lines.append(f"│  Progress: {x['pct']}%")
            lines.append(f"│  <b>Sisa: {format_idr(x['remaining'])}</b>")
            lines.append(f"│  Status: {status_text}")
            lines.append("└────────────────────────────")
        
        await message.answer("\n".join(lines), parse_mode="HTML")
    else:
        # Show all budgets summary
        total_budget = sum(x['amount'] for x in items)
        total_spent = sum(x['spent'] for x in items)
        total_remaining = sum(x['remaining'] for x in items)
        progress_pct = round((total_spent / total_budget * 100) if total_budget > 0 else 0)
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            f"  <b>🎯 Budget {period_label(period)}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"Total: <code>{format_idr(total_budget)}</code>",
            f"Terpakai: <code>{format_idr(total_spent)}</code> ({progress_pct}%)",
        ]
        
        remaining_emoji = "💚" if progress_pct < 70 else "⚡" if progress_pct < 90 else "🔴"
        lines.append(f"{remaining_emoji} Sisa: <code>{format_idr(total_remaining)}</code>")
        
        lines.append("")
        lines.append("┌─ <b>DETAIL PER KATEGORI</b>")
        
        # Show over budget first
        over_items = [x for x in items if x['over']]
        if over_items:
            lines.append("│")
            lines.append("│ ⚠️ <b>OVER BUDGET:</b>")
            for x in over_items:
                lines.append(f"│ 🔴 {x['name']}")
                lines.append(f"│   {format_idr(x['spent'])} / {format_idr(x['amount'])} ({x['pct']}%)")
                lines.append(f"│   Over: {format_idr(abs(x['remaining']))}")
        
        # Show normal items
        normal_items = [x for x in items if not x['over']]
        if normal_items:
            if over_items:
                lines.append("│")
                lines.append("│ ✅ <b>DALAM BATAS:</b>")
            for x in normal_items:
                emoji = "💚" if x['pct'] < 70 else "⚡"
                lines.append(f"│ {emoji} {x['name']}")
                lines.append(f"│   {format_idr(x['spent'])} / {format_idr(x['amount'])} ({x['pct']}%)")
                lines.append(f"│   Sisa: {format_idr(x['remaining'])}")
        
        lines.append("└────────────────────────────")
        
        await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("kategori"))
async def cmd_kategori(message: Message) -> None:
    if not _allowed(message.chat.id):
        return

    with SessionLocal() as db:
        from app.models import Category
        from sqlalchemy import select
        
        categories = db.scalars(select(Category).order_by(Category.kind, Category.name)).all()
        
        if not categories:
            await message.reply(
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  <b>📁 Kategori</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Belum ada kategori.\n\n"
                "<b>Tambah kategori:</b>\n"
                "• <code>tambah kategori Makanan</code>\n"
                "• <code>kategori baru Transport income</code>\n"
                "• <code>buat kategori Gaji income</code>",
                parse_mode="HTML"
            )
            return
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>📁 Kategori</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        expense_cats = [c for c in categories if c.kind == "expense"]
        income_cats = [c for c in categories if c.kind == "income"]
        
        if expense_cats:
            lines.append("<b>📉 Pengeluaran</b>")
            for cat in expense_cats:
                lines.append(f"  • {cat.name}")
            lines.append("")
        
        if income_cats:
            lines.append("<b>📈 Pemasukan</b>")
            for cat in income_cats:
                lines.append(f"  • {cat.name}")
            lines.append("")
        
        lines.append("<i>Kelola kategori:</i>")
        lines.append("• <code>tambah kategori [nama]</code>")
        lines.append("• <code>hapus kategori [nama]</code>")
        lines.append("• <code>ubah kategori [lama] jadi [baru]</code>")
        
        await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("import"))
async def cmd_import(message: Message) -> None:
    if not _allowed(message.chat.id):
        return

    await message.reply(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>📥 Import CSV</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim file CSV dengan format:\n\n"
        "<b>Format 1 (lengkap):</b>\n"
        "<code>tanggal,nominal,kategori,merchant,dompet</code>\n\n"
        "<b>Format 2 (minimal):</b>\n"
        "<code>tanggal,nominal,kategori</code>\n\n"
        "<b>Contoh:</b>\n"
        "<code>2024-01-15,50000,Makanan,Indomaret,Cash\n"
        "2024-01-16,100000,Transport,Grab,GoPay</code>\n\n"
        "<i>Format tanggal: YYYY-MM-DD atau DD/MM/YYYY</i>",
        parse_mode="HTML"
    )


@router.message(F.document)
async def handle_document(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    
    doc = message.document
    if not doc or not doc.file_name:
        return
    
    # Check if CSV
    if not doc.file_name.lower().endswith('.csv'):
        await message.reply("❌ Hanya file CSV yang didukung")
        return
    
    # Download file
    file = await message.bot.download(doc.file_id)
    if not file:
        await message.reply("❌ Gagal download file")
        return
    
    content = file.read().decode('utf-8-sig')
    
    # Parse and import
    with SessionLocal() as db:
        result = await _import_csv(db, content, message)
        await message.reply(result, parse_mode="HTML")


@router.message(Command("pengeluaran", "pemasukan"))
async def handle_totals(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    with SessionLocal() as db:
        data = ledger.summary(db, current_period())
    key = "expense" if message.text.lower().startswith("/pengeluaran") else "income"
    label = "Pengeluaran" if key == "expense" else "Pemasukan"
    await message.answer(f"{label} bulan ini: <b>{format_idr(data[key])}</b>")


async def _period_report(message: Message, scope: str) -> None:
    if not _allowed(message.chat.id):
        return
    with SessionLocal() as db:
        data = ledger.named_range_summary(db, scope)
    await message.answer(
        f"<b>Ringkasan {data['label']}</b>\n"
        f"Pemasukan: <b>{format_idr(data['income'])}</b>\n"
        f"Pengeluaran: <b>{format_idr(data['expense'])}</b>\n"
        f"Cashflow: <b>{format_idr(data['net'])}</b>\n"
        f"Transaksi: {data['count']}"
    )


@router.message(Command("harian"))
async def handle_daily(message: Message) -> None:
    await _period_report(message, "day")


@router.message(Command("mingguan"))
async def handle_weekly(message: Message) -> None:
    await _period_report(message, "week")


@router.message(Command("bulanan"))
async def handle_monthly(message: Message) -> None:
    await _period_report(message, "month")


@router.message(EditAmount.waiting)
async def handle_new_amount(message: Message, state: FSMContext) -> None:
    if not _allowed(message.chat.id):
        return

    amount = parse_amount(message.text)
    if not amount or amount <= 0:
        await message.reply("Nominal tidak dikenali. Contoh: 47500 atau 47.500")
        return

    data = await state.get_data()
    await state.clear()

    with SessionLocal() as db:
        transaction = db.get(Transaction, data.get("tx_id"))
        if transaction is None or transaction.deleted_at is not None:
            await message.reply("Transaksi sudah tidak ada.")
            return

        transaction.amount = amount
        db.commit()
        wallet.sync_balances(db)

        text, keyboard = _render(db, transaction)

    await message.reply(text, reply_markup=keyboard)


async def _process_image(message: Message, bot: Bot, image_bytes: bytes) -> None:
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    status = await message.reply("Membaca struk...")

    try:
        with SessionLocal() as db:
            transaction, data = await ingest.draft_from_photo(
                db,
                image_bytes,
                chat_id=message.chat.id,
                message_id=message.message_id,
                update_id=message.message_id,
            )

            if transaction is None:
                logger.warning(
                    "Gagal buat draft dari foto: lines=%s confidence=%s merchant=%s amount=%s",
                    len(data.raw_text.splitlines()) if data.raw_text else 0,
                    data.confidence,
                    data.merchant,
                    data.amount,
                )
                await status.edit_text(
                    "Struk belum bisa dibaca. Coba foto lebih terang dan tegak, "
                    "atau kirim sebagai file JPG/PNG. Bisa juga tulis manual: makan 35rb"
                )
                return

            text, keyboard = _render(db, transaction)
        await status.edit_text(text, reply_markup=keyboard)
    except Exception as exc:
        logger.exception("Error proses foto")
        await status.edit_text(f"Gagal memproses gambar: {exc}")


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot) -> None:
    if not _allowed(message.chat.id):
        return
    photo = message.photo[-1]
    try:
        file = await bot.get_file(photo.file_id)
        stream = await bot.download_file(file.file_path)
        await _process_image(message, bot, stream.read())
    except Exception:
        logger.exception("Gagal mengunduh foto Telegram")
        await message.reply("Foto gagal diunduh. Coba kirim ulang.")

@router.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    if not _allowed(message.chat.id) or not message.document:
        return
    mime = message.document.mime_type or ""
    name = (message.document.file_name or "").lower()
    if not (mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"))):
        await message.reply("Kirim file gambar JPG, PNG, WEBP, BMP, atau TIFF.")
        return
    try:
        file = await bot.get_file(message.document.file_id)
        stream = await bot.download_file(file.file_path)
        await _process_image(message, bot, stream.read())
    except Exception:
        logger.exception("Gagal mengunduh dokumen Telegram")
        await message.reply("Gambar gagal diunduh. Coba kirim ulang.")

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    if not _allowed(message.chat.id):
        return

    text = (message.text or "").strip()
    question = text.lower()
    
    # Check if user sedang edit nominal budget
    chat_id = message.chat.id
    if chat_id in _budget_edit_state:
        amount = extract_amount(text)
        if amount:
            category_id = _budget_edit_state[chat_id]["category_id"]
            del _budget_edit_state[chat_id]
            
            with SessionLocal() as db:
                preview_text, keyboard = _render_budget_preview(db, category_id, amount)
            
            await message.reply(preview_text, reply_markup=keyboard)
            return
        else:
            await message.reply("❌ Nominal tidak valid. Coba lagi atau /cancel")
            return
    
    # CRUD Kategori: tambah, hapus, ubah
    if any(word in question for word in ("tambah kategori", "kategori baru", "buat kategori")):
        with SessionLocal() as db:
            await _handle_add_category(db, text, message)
        return
    
    if any(word in question for word in ("hapus kategori", "delete kategori")):
        with SessionLocal() as db:
            await _handle_delete_category(db, text, message)
        return
    
    if "ubah kategori" in question and "jadi" in question:
        with SessionLocal() as db:
            await _handle_rename_category(db, text, message)
        return
    
    # Check if setting budget: "budget makanan 2jt", "atur budget transportasi 500rb"
    if any(word in question for word in ("budget", "anggaran")):
        amount = extract_amount(text)
        if amount:
            # Parse budget command
            with SessionLocal() as db:
                await _handle_budget_set(db, text, amount, message)
            return
    
    # Query info dan finance question HARUS sebelum draft transaksi
    # Check dulu apakah ini pertanyaan (tanpa nominal) atau transaksi (ada nominal)
    has_amount = extract_amount(text) is not None
    
    # Jika tidak ada nominal, prioritaskan sebagai query/pertanyaan
    if not has_amount:
        # Query info - "berapa kategori", "total transaksi", "kategori apa saja"
        with SessionLocal() as db:
            query_result = await _handle_info_query(db, question)
            if query_result:
                await message.reply(query_result, parse_mode="HTML")
                return
        
        # Finance questions - "berapa saldo", "pengeluaran bulan ini"
        finance_answer = _answer_finance_question(question)
        if finance_answer:
            await message.reply(finance_answer)
            return
        
        # Ringkasan kondisi keuangan
        if any(word in question for word in ("kondisi keuangan", "ringkas", "keuangan saya", "cashflow")):
            await message.reply(_financial_summary())
            return
        
        # Default: bantu user jika tidak mengerti
        if any(word in question for word in ("bantu", "help", "tutorial", "cara", "apa")):
            await message.reply(HELP_TEXT)
            return
    
    # Jika ada nominal DAN bukan pertanyaan budget, masuk ke draft transaksi
    with SessionLocal() as db:
        transaction = await ingest.draft_from_text(
            db,
            text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            update_id=message.message_id,
        )

        if transaction is None:
            await message.reply(
                "Nominal tidak ditemukan. Tulis seperti: makan siang 35rb"
            )
            return

        text, keyboard = _render(db, transaction)

    await message.reply(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("tx:ok:"))
async def callback_confirm(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None or transaction.deleted_at is not None:
            await callback.answer("❌ Transaksi tidak ditemukan", show_alert=True)
            return
        if transaction.amount <= 0:
            await callback.answer("⚠️ Nominal belum diisi", show_alert=True)
            return

        transaction.status = "confirmed"
        if transaction.merchant and transaction.category_id:
            remember_merchant(db, transaction.merchant, transaction.category_id)
        db.commit()
        wallet.sync_balances(db)

        category = db.get(Category, transaction.category_id) if transaction.category_id else None
        account = db.get(Account, transaction.account_id) if transaction.account_id else None
        
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>✅ Tersimpan</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        if transaction.merchant:
            lines.append(f"🏪  {html.escape(transaction.merchant)}")
        
        lines.append(f"💰  <code>{format_idr(transaction.amount)}</code>")
        lines.append(f"📁  {html.escape(category.name) if category else '-'}")
        lines.append(f"👛  {html.escape(account.name) if account else '-'}")
        lines.append(f"🕐  {format_dt(transaction.occurred_at)}")
        
        text = "\n".join(lines)
        
        # Check budget alerts
        if transaction.kind == "expense":
            await check_and_send_alerts(db, callback.bot, callback.message.chat.id, current_period())

    await callback.message.edit_text(text, reply_markup=None)
    await callback.answer("✅ Tersimpan")


@router.callback_query(F.data.startswith("tx:no:"))
async def callback_cancel(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            await callback.answer("❌ Transaksi tidak ditemukan", show_alert=True)
            return
        
        category = db.get(Category, transaction.category_id) if transaction.category_id else None
        account = db.get(Account, transaction.account_id) if transaction.account_id else None

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "  <b>🗑️ Konfirmasi Hapus</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        if transaction.merchant:
            lines.append(f"🏪  {html.escape(transaction.merchant)}")
        
        lines.append(f"💰  <code>{format_idr(transaction.amount)}</code>")
        lines.append(f"📁  {html.escape(category.name) if category else '-'}")
        lines.append(f"👛  {html.escape(account.name) if account else '-'}")
        lines.append(f"🕐  {format_dt(transaction.occurred_at)}")
        
        if transaction.note:
            lines.append(f"📝  {html.escape(transaction.note)}")
        
        lines.append("")
        lines.append("⚠️ <i>Yakin hapus transaksi ini?</i>")
        
        text = "\n".join(lines)
        
        buttons = [
            [
                InlineKeyboardButton(text="🗑️ Ya, Hapus", callback_data=f"tx:delete:{transaction_id}"),
                InlineKeyboardButton(text="❌ Batal", callback_data=f"tx:back:{transaction_id}")
            ]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("tx:delete:"))
async def callback_delete_confirm(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            await callback.answer("❌ Transaksi tidak ditemukan", show_alert=True)
            return

        merchant = transaction.merchant or "Transaksi"
        amount = transaction.amount
        
        transaction.status = "rejected"
        transaction.deleted_at = utcnow()
        db.commit()
        wallet.sync_balances(db)

    result = (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>✅ Berhasil Dihapus</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏪  {html.escape(merchant)}\n"
        f"💰  <code>{format_idr(amount)}</code>"
    )
    
    await callback.message.edit_text(result, reply_markup=None)
    await callback.answer("✅ Transaksi dihapus")


@router.message(Command("hapus", "delete"))
async def cmd_hapus(message: Message, state: FSMContext) -> None:
    """Command untuk hapus transaksi - show mode selection (single/multiple)."""
    if not _allowed(message.chat.id):
        return

    with SessionLocal() as db:
        # Get recent transactions
        transactions = list(
            db.scalars(
                select(Transaction)
                .where(
                    Transaction.chat_id == message.chat.id,
                    Transaction.deleted_at == None
                )
                .order_by(Transaction.occurred_at.desc())
                .limit(15)
            ).all()
        )

    if not transactions:
        await message.reply("❌ Belum ada transaksi tersedia.")
        return

    await state.update_data(mode="hapus")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📍 Single", callback_data="hapus_mode:single"),
            InlineKeyboardButton(text="📋 Multiple", callback_data="hapus_mode:multi")
        ],
        [InlineKeyboardButton(text="✖️ Batal", callback_data="hapus_cancel")]
    ])

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>Pilih Mode Penghapusan</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "• <b>Single</b> — hapus satu transaksi\n"
        "• <b>Multiple</b> — hapus beberapa transaksi sekaligus"
    )

    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("tx_hapus:"))
async def callback_hapus_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start proses hapus transaksi - pilih mode (single/multiple)."""
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return
    
    await state.update_data(mode="hapus")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Single 📍", callback_data="hapus_mode:single"),
            InlineKeyboardButton(text="Multiple 📋", callback_data="hapus_mode:multi")
        ],
        [InlineKeyboardButton(text="❌ Batal", callback_data="hapus_cancel")]
    ])
    
    await callback.message.edit_text(
        "Pilih mode penghapusan:\n\n"
        "• <b>Single</b> — hapus satu transaksi\n"
        "• <b>Multiple</b> — hapus beberapa transaksi sekaligus",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hapus_mode:"))
async def callback_hapus_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle mode penghapusan (single/multiple)."""
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return
    
    mode = callback.data.split(":")[1]
    await state.update_data(mode=mode)
    
    if mode == "single":
        # Show transaction list for single selection
        with SessionLocal() as db:
            transactions = list(
                db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.chat_id == callback.message.chat.id,
                        Transaction.deleted_at == None
                    )
                    .order_by(Transaction.occurred_at.desc())
                    .limit(15)
                ).all()
            )
        await _send_transaction_selection(callback.message, transactions, "hapus_single", "Pilih 1 transaksi:")
    else:
        # Show transaction list for multiple selection
        with SessionLocal() as db:
            transactions = list(
                db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.chat_id == callback.message.chat.id,
                        Transaction.deleted_at == None
                    )
                    .order_by(Transaction.occurred_at.desc())
                    .limit(15)
                ).all()
            )
        await state.update_data(selected_tx_ids=[])
        await _send_transaction_selection(callback.message, transactions, "hapus_multi", "Pilih transaksi (multiple):")
    
    await callback.answer()


@router.callback_query(F.data.startswith("hapus_cancel"))
async def callback_hapus_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Batal proses hapus."""
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return
    
    await state.update_data(mode=None, selected_tx_ids=[], tx_id=None)
    
    await callback.message.edit_text(
        "❌ Penghapusan dibatalkan.",
        reply_markup=None
    )
    await callback.answer()


async def _send_transaction_selection(message: Message, transactions: list, prefix: str, header: str) -> None:
    """Kirim daftar transaksi dengan keyboard untuk seleksi."""
    if not transactions:
        await message.reply("❌ Belum ada transaksi tersedia.", reply_markup=None)
        return
    
    text = f"━━━━━━━━━━━━━━━━━━━━━━━\n  <b>{header}</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    keyboard_rows = []
    
    for tx in transactions:
        date_str = format_dt(tx.occurred_at).split(",")[0].strip()
        merchant = tx.merchant or "Tanpa merchant"
        amount = format_idr(tx.amount)
        
        text += f"• {date_str} - {amount}\n  {merchant}\n\n"
        
        keyboard_rows.append(
            InlineKeyboardButton(
                text=f"{amount}",
                callback_data=f"{prefix}:{tx.id}"
            )
        )
    
    # Group buttons in rows of 2
    keyboard = []
    row = []
    for btn in keyboard_rows:
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    if keyboard:
        keyboard.append([
            InlineKeyboardButton(text="⬅️ Kembali", callback_data="hapus_cancel")
        ])
    
    await message.reply(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")


@router.callback_query(F.data.startswith("hapus_single:"))
async def callback_hapus_single(callback: CallbackQuery) -> None:
    """Hapus single transaksi."""
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return
    
    tx_id = int(callback.data.split(":")[1])
    
    with SessionLocal() as db:
        transaction = db.get(Transaction, tx_id)
        if transaction is None:
            await callback.answer("❌ Transaksi tidak ditemukan", show_alert=True)
            return
        
        merchant = transaction.merchant or "Transaksi"
        amount = transaction.amount
        
        transaction.status = "rejected"
        transaction.deleted_at = utcnow()
        db.commit()
        wallet.sync_balances(db)
    
    result = (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>✅ Berhasil Dihapus</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏪  {html.escape(merchant)}\n"
        f"💰  <code>{format_idr(amount)}</code>"
    )
    
    await callback.message.edit_text(result, reply_markup=None)
    await callback.answer("✅ Transaksi dihapus")


@router.callback_query(F.data.startswith("hapus_multi:"))
async def callback_hapus_multi(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle seleksi transaksi untuk dihapus (multiple)."""
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return
    
    tx_id = int(callback.data.split(":")[1])
    
    data = await state.get_data()
    selected_ids = data.get("selected_tx_ids", [])
    
    if tx_id in selected_ids:
        selected_ids.remove(tx_id)
    else:
        selected_ids.append(tx_id)
    
    await state.update_data(selected_tx_ids=selected_ids)
    
    # Update message dengan daftar yang dipilih
    with SessionLocal() as db:
        transactions = list(
            db.scalars(
                select(Transaction)
                .where(Transaction.id.in_(selected_ids))
                .all()
            ).all()
        )
    
    await _update_hapus_multi_message(callback.message, transactions, selected_ids)
    await callback.answer()


async def _update_hapus_multi_message(message: Message, transactions: list, selected_ids: list) -> None:
    """Update pesan dengan daftar transaksi yang dipilih."""
    text = "━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"  <b>🗑️ Hapus ({len(selected_ids)})</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    total_amount = 0
    for tx in transactions:
        total_amount += tx.amount
        date_str = format_dt(tx.occurred_at).split(",")[0].strip()
        merchant = tx.merchant or "Tanpa merchant"
        text += f"• {date_str} - {format_idr(tx.amount)}\n"
        text += f"  {merchant}\n\n"
    
    if selected_ids:
        text += f"<b>Total: {format_idr(total_amount)}</b>\n\n"
    
    text += "Kirim /hapus_confirm untuk menghapus.\natau /hapus_cancel untuk batal."
    
    keyboard_rows = []
    for tx in transactions:
        keyboard_rows.append(
            InlineKeyboardButton(
                text=f"❌ {format_idr(tx.amount)}",
                callback_data=f"hapus_multi_rem:{tx.id}"
            )
        )
    
    keyboard = []
    row = []
    for btn in keyboard_rows:
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    if keyboard:
        keyboard.append([
            InlineKeyboardButton(text="✔️ Konfirmasi Hapus", callback_data="hapus_multi_confirm")
        ])
        keyboard.append([
            InlineKeyboardButton(text="✖️ Batal", callback_data="hapus_cancel")
        ])
    
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")


@router.callback_query(F.data.startswith("hapus_multi_rem:"))
async def callback_hapus_multi_rem(callback: CallbackQuery, state: FSMContext) -> None:
    """Hapus ID dari seleksi multiple."""
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return
    
    tx_id = int(callback.data.split(":")[1])
    
    data = await state.get_data()
    selected_ids = data.get("selected_tx_ids", [])
    
    if tx_id in selected_ids:
        selected_ids.remove(tx_id)
        await state.update_data(selected_tx_ids=selected_ids)
    
    with SessionLocal() as db:
        transactions = list(
            db.scalars(
                select(Transaction)
                .where(Transaction.id.in_(selected_ids))
                .all()
            ).all()
        )
    
    await _update_hapus_multi_message(callback.message, transactions, selected_ids)
    await callback.answer()


@router.callback_query(F.data == "hapus_multi_confirm")
async def callback_hapus_multi_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Konfirmasi hapus multiple transaksi."""
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return
    
    data = await state.get_data()
    selected_ids = data.get("selected_tx_ids", [])
    
    if not selected_ids:
        await callback.answer("❌ Belum ada transaksi dipilih", show_alert=True)
        return
    
    with SessionLocal() as db:
        transactions = list(
            db.scalars(
                select(Transaction)
                .where(
                    Transaction.id.in_(selected_ids),
                    Transaction.deleted_at == None
                )
            ).all()
        )
        
        for tx in transactions:
            tx.status = "rejected"
            tx.deleted_at = utcnow()
        
        db.commit()
        wallet.sync_balances(db)
        
        total_amount = sum(tx.amount for tx in transactions)
        
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  <b>✅ {len(transactions)} Transaksi Dihapus</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰  <code>{format_idr(total_amount)}</code>",
            reply_markup=None
        )
    
    await state.update_data(selected_tx_ids=[])
    await callback.answer(f"✅ {len(transactions)} transaksi dihapus")


@router.message(Command("hapus_cancel"))
async def cmd_hapus_cancel(message: Message, state: FSMContext) -> None:
    """Command cancel untuk proses hapus."""
    if not _allowed(message.chat.id):
        return
    
    await state.update_data(mode=None, selected_tx_ids=[])
    await message.reply("❌ Dibatalkan", reply_markup=None)


@router.message(Command("hapus_confirm"))
async def cmd_hapus_confirm(message: Message, state: FSMContext) -> None:
    """Command konfirmasi untuk proses hapus."""
    if not _allowed(message.chat.id):
        return
    
    data = await state.get_data()
    selected_ids = data.get("selected_tx_ids", [])
    
    if not selected_ids:
        await message.reply("❌ Belum ada transaksi dipilih", reply_markup=None)
        return
    
    with SessionLocal() as db:
        transactions = list(
            db.scalars(
                select(Transaction)
                .where(
                    Transaction.id.in_(selected_ids),
                    Transaction.deleted_at == None
                )
            ).all()
        )
        
        for tx in transactions:
            tx.status = "rejected"
            tx.deleted_at = utcnow()
        
        db.commit()
        wallet.sync_balances(db)
        
        total_amount = sum(tx.amount for tx in transactions)
        
        await message.reply(
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  <b>✅ {len(transactions)} Transaksi Dihapus</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰  <code>{format_idr(total_amount)}</code>"
        )
    
    await state.update_data(selected_tx_ids=[])
async def callback_amount(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])
    await state.set_state(EditAmount.waiting)
    await state.update_data(tx_id=transaction_id)

    await callback.message.reply("Ketik nominal yang benar. Contoh: 47500")
    await callback.answer()


@router.callback_query(F.data.startswith("tx:cat:"))
async def callback_categories(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        transaction_kind = transaction.kind if transaction and transaction.kind in ("income", "expense") else "expense"
        categories = list(
            db.scalars(
                select(Category)
                .where(Category.kind == transaction_kind)
                .order_by(Category.sort_order)
            ).all()
        )

    await callback.message.edit_reply_markup(
        reply_markup=_category_keyboard(transaction_id, categories)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tx:setcat:"))
async def callback_set_category(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    _prefix, _action, raw_transaction_id, raw_category_id = callback.data.split(":")
    transaction_id = int(raw_transaction_id)
    category_id = int(raw_category_id)

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None or transaction.deleted_at is not None:
            await callback.answer("❌ Transaksi tidak ditemukan", show_alert=True)
            return

        transaction.category_id = category_id
        transaction.category_source = "manual"
        if transaction.merchant:
            remember_merchant(db, transaction.merchant, category_id)
        db.commit()

        text, keyboard = _render(db, transaction)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("✅ Kategori diubah")


@router.callback_query(F.data.startswith("tx:back:"))
async def callback_back(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            await callback.answer("❌ Transaksi tidak ditemukan", show_alert=True)
            return
        text, keyboard = _render(db, transaction)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("cat_add_type:"))
async def callback_category_add_type(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":", 2)
    name = parts[1]
    kind = parts[2]
    
    kind_text = "📈 Pemasukan" if kind == "income" else "📉 Pengeluaran"
    
    # Tampilkan konfirmasi final
    buttons = [
        [
            InlineKeyboardButton(text="✅ Ya, Buat", callback_data=f"cat_add_confirm:{name}:{kind}"),
            InlineKeyboardButton(text="❌ Batal", callback_data="cat_cancel")
        ]
    ]
    
    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>Konfirmasi Tambah</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📁  <b>{name}</b>\n"
        f"📊  {kind_text}\n\n"
        "Lanjutkan?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat_add_confirm:"))
async def callback_category_add_confirm(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    name = parts[1]
    kind = parts[2]
    
    with SessionLocal() as db:
        from app.models import Category
        from sqlalchemy import select
        
        # Check lagi duplicate sebelum save
        existing = db.scalar(select(Category).where(Category.name == name))
        if existing:
            await callback.answer("❌ Kategori sudah ada", show_alert=True)
            return
        
        category = Category(name=name, kind=kind)
        db.add(category)
        db.commit()
        
        kind_text = "📈 Pemasukan" if kind == "income" else "📉 Pengeluaran"
        
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  <b>✅ Kategori Dibuat</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁  {name}\n"
            f"📊  {kind_text}",
            reply_markup=None
        )
        await callback.answer("✅ Kategori dibuat")


@router.callback_query(F.data.startswith("cat_del_confirm:"))
async def callback_category_delete_confirm(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    category_id = int(parts[1])
    
    with SessionLocal() as db:
        from app.models import Category
        from app.services import cleanup

        category = db.get(Category, category_id)
        if not category:
            await callback.answer("❌ Kategori tidak ditemukan", show_alert=True)
            return

        name = category.name
        result = cleanup.delete_category(db, category_id)
        if not result.deleted:
            await callback.answer(
                f"⚠️ Kategori dipakai di {result.active_transactions} transaksi aktif",
                show_alert=True,
            )
            return

        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  <b>✅ Kategori Dihapus</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁  {name}",
            reply_markup=None
        )
        await callback.answer("✅ Kategori dihapus")


@router.callback_query(F.data == "cat_cancel")
async def callback_category_cancel(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    
    await callback.message.edit_text("❌ Dibatalkan", reply_markup=None)
    await callback.answer()


@router.callback_query(F.data.startswith("cat_rename_confirm:"))
async def callback_category_rename_confirm(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":", 2)
    category_id = int(parts[1])
    new_name = parts[2]
    
    with SessionLocal() as db:
        from app.models import Category
        
        category = db.get(Category, category_id)
        if not category:
            await callback.answer("❌ Kategori tidak ditemukan", show_alert=True)
            return
        
        old_name = category.name
        category.name = new_name
        db.commit()
        
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  <b>✅ Kategori Diubah</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁  {old_name} → {new_name}",
            reply_markup=None
        )
        await callback.answer("✅ Kategori diubah")


@router.callback_query(F.data.startswith("budget_edit_cat:"))
async def callback_budget_edit_category(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    current_category_id = int(parts[1])
    amount = int(parts[2])

    with SessionLocal() as db:
        from app.models import Category
        from sqlalchemy import select
        
        categories = db.scalars(
            select(Category).where(Category.kind == "expense")
        ).all()
        
        buttons = []
        for cat in categories:
            text = f"{'✓ ' if cat.id == current_category_id else ''}{cat.name}"
            buttons.append([InlineKeyboardButton(
                text=text,
                callback_data=f"budget_set_cat:{cat.id}:{amount}"
            )])
        
        buttons.append([InlineKeyboardButton(
            text="« Kembali",
            callback_data=f"budget_back:{current_category_id}:{amount}"
        )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>📁 Pilih Kategori</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Pilih kategori untuk budget:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("budget_set_cat:"))
async def callback_budget_set_category(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    category_id = int(parts[1])
    amount = int(parts[2])

    with SessionLocal() as db:
        text, keyboard = _render_budget_preview(db, category_id, amount)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("✅ Kategori diubah")


@router.callback_query(F.data.startswith("budget_edit_amt:"))
async def callback_budget_edit_amount(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    category_id = int(parts[1])

    # Store state untuk next message
    chat_id = callback.message.chat.id
    _budget_edit_state[chat_id] = {"category_id": category_id}

    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  <b>Input Nominal</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 Ketik nominal budget baru\n\n"
        "<i>Contoh: 2jt, 500rb, 3000000</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Batal", callback_data=f"budget_cancel")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("budget_back:"))
async def callback_budget_back(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    category_id = int(parts[1])
    amount = int(parts[2])

    with SessionLocal() as db:
        text, keyboard = _render_budget_preview(db, category_id, amount)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("budget_confirm:"))
async def callback_budget_confirm(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    category_id = int(parts[1])
    amount = int(parts[2])

    with SessionLocal() as db:
        category = db.get(Category, category_id)
        if not category:
            await callback.answer("❌ Kategori tidak ditemukan", show_alert=True)
            return

        period = current_period()
        existing = db.scalar(
            select(Budget).where(
                Budget.category_id == category_id,
                Budget.period == period
            )
        )

        if existing:
            existing.amount = amount
            action = "diperbarui"
        else:
            db.add(Budget(category_id=category_id, period=period, amount=amount))
            action = "dibuat"

        db.commit()

        result = (
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  <b>✅ Budget {action.capitalize()}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁  {html.escape(category.name)}\n"
            f"💰  <code>{format_idr(amount)}</code>\n"
            f"📅  {period_label(period)}"
        )
        
        await callback.message.edit_text(result, reply_markup=None)
        await callback.answer(f"Budget {action}")


@router.callback_query(F.data == "budget_cancel")
async def callback_budget_cancel(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    await callback.message.edit_text("❌ Dibatalkan", reply_markup=None)
    await callback.answer("❌ Dibatalkan")


@router.callback_query(F.data.startswith("budget_category:"))
async def callback_budget_category(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    parts = callback.data.split(":")
    category_id = int(parts[1])
    amount = int(parts[2])

    with SessionLocal() as db:
        category = db.get(Category, category_id)
        if not category:
            await callback.answer("❌ Kategori tidak ditemukan", show_alert=True)
            return

        period = current_period()
        existing = db.scalar(
            select(Budget).where(
                Budget.category_id == category_id,
                Budget.period == period
            )
        )

        action = "update" if existing else "buat"
        old_text = f"\nSebelumnya: {format_idr(existing.amount)}" if existing else ""

        buttons = [
            [
                InlineKeyboardButton(text="✅ Konfirmasi", callback_data=f"budget_confirm:{category_id}:{amount}"),
                InlineKeyboardButton(text="❌ Batal", callback_data="budget_cancel")
            ]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            f"<b>Konfirmasi Budget</b>\n\n"
            f"Kategori: <b>{category.name}</b>\n"
            f"Jumlah: <b>{format_idr(amount)}</b>\n"
            f"Periode: <b>{period_label(period)}</b>{old_text}\n\n"
            f"Aksi: <b>{action.capitalize()} budget</b>",
            reply_markup=keyboard
        )
        await callback.answer()


async def start_bot() -> None:
    """Dipanggil dari lifespan FastAPI."""
    global bot_instance
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    bot_instance = bot
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)

    if settings.telegram_chat_id is None:
        logger.warning("TELEGRAM_ALLOWED_CHAT_ID belum diisi, bot akan mengabaikan semua pesan.")

    try:
        me = await bot.get_me()
        logger.info("Bot @%s aktif.", me.username)
        await dispatcher.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Bot Telegram berhenti: %s", exc)
    finally:
        bot_instance = None
        await bot.session.close()
