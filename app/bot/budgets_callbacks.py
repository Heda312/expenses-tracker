"""Callback konfirmasi budget (budget_*).

Dipisah dari budgets.py agar urutan registrasi callback query sama dengan
app/bot.py asli: blok ini terdaftar paling akhir.
"""

import html

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.bot.common import _allowed, _budget_edit_state, router
from app.bot.render import _render_budget_preview
from app.db import SessionLocal
from app.models import Budget, Category
from app.services.dates import current_period, period_label
from app.services.money import format_idr


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
