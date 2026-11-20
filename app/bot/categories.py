"""Perintah /kategori dan CRUD kategori dari natural-language."""

from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.orm import Session

from app.bot.common import _allowed, router
from app.db import SessionLocal


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
