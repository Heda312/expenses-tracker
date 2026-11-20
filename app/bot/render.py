"""Render preview transaksi/budget dan ringkasan keuangan."""

import html

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.orm import Session

from app.bot.keyboards import _keyboard
from app.db import SessionLocal
from app.models import Account, Category, Transaction
from app.services import ledger
from app.services.dates import current_period, format_dt, period_label
from app.services.money import format_idr

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
