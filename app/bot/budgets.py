"""Perintah /budget dan set budget dari natural-language."""

from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.orm import Session

from app.bot.common import _allowed, router
from app.bot.render import _render_budget_preview
from app.db import SessionLocal
from app.services import ledger
from app.services.dates import current_period, period_label
from app.services.money import format_idr


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
