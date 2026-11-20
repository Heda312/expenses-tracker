"""Alur hapus transaksi: /hapus, /hapus_cancel, /hapus_confirm dan callback hapus_*."""

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
from sqlalchemy import select

from app.bot.common import _allowed, router
from app.db import SessionLocal
from app.models import Transaction, utcnow
from app.services import wallet
from app.services.dates import format_dt
from app.services.money import format_idr


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
