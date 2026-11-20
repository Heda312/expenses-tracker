"""Import CSV dan callback konfirmasi draft transaksi (tx:ok/no/delete)."""

import html

from aiogram import F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.orm import Session

from app.bot.common import EditAmount, _allowed, router
from app.db import SessionLocal
from app.models import Account, Category, Transaction, utcnow
from app.services import wallet
from app.services.budget_alerts import check_and_send_alerts
from app.services.dates import current_period, format_dt
from app.services.merchant import remember_merchant
from app.services.money import format_idr


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
async def handle_csv_document(message: Message) -> None:
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

# Catatan: sengaja tanpa decorator router -- pada app/bot.py asli fungsi
# ini tidak terdaftar di router. Dipertahankan apa adanya.
async def callback_amount(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None or not _allowed(callback.message.chat.id):
        await callback.answer("🚫 Tidak diizinkan", show_alert=True)
        return

    transaction_id = int(callback.data.split(":")[2])
    await state.set_state(EditAmount.waiting)
    await state.update_data(tx_id=transaction_id)

    await callback.message.reply("Ketik nominal yang benar. Contoh: 47500")
    await callback.answer()
