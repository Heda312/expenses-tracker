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

from app.config import settings
from app.db import SessionLocal
from app.models import Account, Category, Transaction, utcnow
from app.services import ingest
from app.services.dates import format_dt
from app.services.merchant import remember_merchant
from app.services.money import extract_amount, format_idr, parse_amount
from app.services import ledger
from app.services.dates import current_period, now_local, to_utc, shift_period, month_bounds

logger = logging.getLogger(__name__)
router = Router()
bot_instance: Bot | None = None

# Media group queue: {chat_id: {group_id: [(message_id, bytes), ...]}}
_media_group_queue: dict[int, dict[str, list[tuple[int, bytes]]]] = {}
_media_group_timeout: dict[str, asyncio.Task] = {}


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
    "Kirim foto struk, atau tulis transaksi langsung.\n\n"
    "Contoh:\n"
    "  makan siang 35rb\n"
    "  parkir 5rb pake gopay\n"
    "  gaji 8jt masuk bca\n\n"
    "Setiap hasil akan ditampilkan dulu untuk dikonfirmasi.\n\n"
    "Perintah laporan:\n"
    "/ringkasan - kondisi keuangan bulan ini\n"
    "/saldo - saldo semua dompet\n"
    "/budget - status budget\n"
    "/pengeluaran - total pengeluaran bulan ini\n"
    "/pemasukan - total pemasukan bulan ini\n"
    "/transaksi - transaksi terakhir\n"
    "/harian - spending dan pemasukan hari ini\n"
    "/mingguan - spending dan pemasukan minggu ini\n"
    "/bulanan - spending dan pemasukan bulan ini\n"
    "Kirim foto struk langsung ke chat untuk diproses otomatis."
)


class EditAmount(StatesGroup):
    waiting = State()


def _allowed(chat_id: int | None) -> bool:
    """Hanya satu chat yang boleh memakai bot ini."""
    return settings.telegram_allowed_chat_id is not None and chat_id == settings.telegram_allowed_chat_id


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

    lines = ["<b>Perlu konfirmasi</b>"]
    if transaction.merchant:
        lines.append(f"Merchant: {html.escape(transaction.merchant)}")
    lines.append(f"Nominal: <b>{format_idr(transaction.amount)}</b>")
    lines.append(f"Kategori: {html.escape(category.name) if category else '-'}")
    lines.append(f"Dompet: {html.escape(account.name) if account else '-'}")
    lines.append(f"Waktu: {format_dt(transaction.occurred_at)}")

    if transaction.confidence is not None:
        lines.append(f"Keyakinan: {round(transaction.confidence * 100)}%")

    if transaction.amount <= 0:
        lines.append("")
        lines.append("Nominal belum terbaca. Tekan Ubah nominal.")

    return "\n".join(lines), _keyboard(transaction.id)


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
        f"<b>Ringkasan {data['label']}</b>",
        f"Pemasukan: <b>{format_idr(data['income'])}</b>",
        f"Pengeluaran: <b>{format_idr(data['expense'])}</b>",
        f"Cashflow: <b>{format_idr(data['net'])}</b>",
        f"Saldo: <b>{format_idr(sum(item['balance'] for item in balances))}</b>",
        f"Rata-rata harian: {format_idr(data['daily_average'])}",
    ]
    if data["top_category"]:
        lines.append(f"Kategori terbesar: {data['top_category']['name']}")
    if budgets:
        over = [item["name"] for item in budgets if item["over"]]
        if over:
            lines.append("Budget terlewati: " + ", ".join(over))
    return "\n".join(lines)


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
    parsed = _question_period(text)
    if not parsed:
        return None
    start, end, label = parsed
    with SessionLocal() as db:
        data = ledger.range_summary(db, start, end)
    lower = text.lower()
    wants_income = any(x in lower for x in ("pemasukan", "pendapatan", "uang masuk"))
    wants_expense = any(x in lower for x in ("pengeluaran", "spending", "belanja", "uang keluar"))
    if wants_income and not wants_expense:
        return f"<b>Pemasukan {label}</b>\nTotal: <b>{format_idr(data['income'])}</b>\nJumlah transaksi: {data['income_count']}"
    if wants_expense and not wants_income:
        return f"<b>Pengeluaran {label}</b>\nTotal: <b>{format_idr(data['expense'])}</b>\nJumlah transaksi: {data['expense_count']}"
    return (f"<b>Kondisi keuangan {label}</b>\nPemasukan: <b>{format_idr(data['income'])}</b> ({data['income_count']} transaksi)\n"
            f"Pengeluaran: <b>{format_idr(data['expense'])}</b> ({data['expense_count']} transaksi)\n"
            f"Cashflow: <b>{format_idr(data['net'])}</b>")


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
    await message.answer("<b>Saldo dompet</b>\n" + "\n".join(f"{x['name']}: {format_idr(x['balance'])}" for x in balances))


@router.message(Command("budget"))
async def handle_budget(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    with SessionLocal() as db:
        items = ledger.budget_progress(db, current_period())
    if not items:
        await message.answer("Belum ada budget bulan ini.")
        return
    await message.answer("<b>Budget bulan ini</b>\n" + "\n".join(f"{x['name']}: {format_idr(x['spent'])} / {format_idr(x['amount'])} ({x['pct']}%)" for x in items))


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

    # Pertanyaan ringkas tanpa nominal dijawab dari data terhitung,
    # bukan ditebak LLM.
    question = (message.text or "").lower()
    # Kalimat transaksi yang mengandung nominal harus masuk draft transaksi,
    # bukan dianggap pertanyaan laporan karena punya kata "kemarin"/"bulan".
    finance_answer = None if extract_amount(message.text or "") else _answer_finance_question(question)
    if finance_answer:
        await message.reply(finance_answer)
        return
    if any(word in question for word in ("kondisi keuangan", "ringkas", "keuangan saya", "cashflow")):
        await message.reply(_financial_summary())
        return

    with SessionLocal() as db:
        transaction = await ingest.draft_from_text(
            db,
            message.text,
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
        await callback.answer("Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None or transaction.deleted_at is not None:
            await callback.answer("Transaksi sudah tidak ada", show_alert=True)
            return
        if transaction.amount <= 0:
            await callback.answer("Nominal belum diisi", show_alert=True)
            return

        transaction.status = "confirmed"
        if transaction.merchant and transaction.category_id:
            remember_merchant(db, transaction.merchant, transaction.category_id)
        db.commit()

        text, _keyboard_unused = _render(db, transaction)

    await callback.message.edit_text(
        text.replace("<b>Perlu konfirmasi</b>", "<b>Tersimpan</b>"),
        reply_markup=None,
    )
    await callback.answer("Tersimpan")


@router.callback_query(F.data.startswith("tx:no:"))
async def callback_cancel(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            await callback.answer("Transaksi sudah tidak ada", show_alert=True)
            return

        transaction.status = "rejected"
        transaction.deleted_at = utcnow()
        db.commit()

    await callback.message.edit_text("Dibatalkan.", reply_markup=None)
    await callback.answer("Dibatalkan")


@router.callback_query(F.data.startswith("tx:amt:"))
async def callback_amount(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])
    await state.set_state(EditAmount.waiting)
    await state.update_data(tx_id=transaction_id)

    await callback.message.reply("Ketik nominal yang benar. Contoh: 47500")
    await callback.answer()


@router.callback_query(F.data.startswith("tx:cat:"))
async def callback_categories(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        categories = list(
            db.scalars(
                select(Category)
                .where(Category.kind == "expense")
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
        await callback.answer("Tidak diizinkan", show_alert=True)
        return

    _prefix, _action, raw_transaction_id, raw_category_id = callback.data.split(":")
    transaction_id = int(raw_transaction_id)
    category_id = int(raw_category_id)

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None or transaction.deleted_at is not None:
            await callback.answer("Transaksi sudah tidak ada", show_alert=True)
            return

        transaction.category_id = category_id
        transaction.category_source = "manual"
        if transaction.merchant:
            remember_merchant(db, transaction.merchant, category_id)
        db.commit()

        text, keyboard = _render(db, transaction)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Kategori diubah")


@router.callback_query(F.data.startswith("tx:back:"))
async def callback_back(callback: CallbackQuery) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])

    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            await callback.answer("Transaksi sudah tidak ada", show_alert=True)
            return
        text, keyboard = _render(db, transaction)

    await callback.message.edit_text(text, reply_markup=keyboard)
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

    if settings.telegram_allowed_chat_id is None:
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
