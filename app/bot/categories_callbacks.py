"""Callback pemilihan kategori draft (tx:cat/setcat/back) dan CRUD kategori (cat_*).

Dipisah dari categories.py agar urutan registrasi callback query sama dengan
app/bot.py asli: blok ini terdaftar setelah delete_flow.
"""

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.bot.common import _allowed, router
from app.bot.keyboards import _category_keyboard
from app.bot.render import _render
from app.db import SessionLocal
from app.models import Category, Transaction
from app.services.merchant import remember_merchant


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
        from app.models import Category, category_color
        from sqlalchemy import select
        
        # Check lagi duplicate sebelum save
        existing = db.scalar(select(Category).where(Category.name == name))
        if existing:
            await callback.answer("❌ Kategori sudah ada", show_alert=True)
            return
        
        category = Category(name=name, kind=kind, color=category_color(name))
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
