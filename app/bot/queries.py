"""Pertanyaan natural-language dan perintah laporan dasar."""

import re
from datetime import datetime, timedelta

from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bot.common import _allowed, router
from app.bot.render import HELP_TEXT, _financial_summary
from app.db import SessionLocal
from app.models import Category, Transaction
from app.services import ledger
from app.services.dates import (
    current_period,
    month_bounds,
    now_local,
    period_label,
    shift_period,
    to_utc,
)
from app.services.money import format_idr


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
