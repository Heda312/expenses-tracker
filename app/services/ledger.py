"""Perhitungan saldo, ringkasan bulanan, budget, dan data chart."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Budget, Category, Transaction
from app.services.dates import current_period, month_bounds, period_label, shift_period, now_local, to_utc
from datetime import datetime, timedelta

ACTIVE = (Transaction.status == "confirmed", Transaction.deleted_at.is_(None))


def _sum(db: Session, *conditions) -> int:
    value = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(*conditions))
    return int(value or 0)


def account_balances(db: Session) -> list[dict]:
    """Saldo tiap dompet = saldo awal + masuk - keluar - transfer keluar + transfer masuk."""
    accounts = db.scalars(select(Account).where(Account.archived.is_(False))).all()
    result = []

    for account in accounts:
        income = _sum(db, Transaction.kind == "income", Transaction.account_id == account.id, *ACTIVE)
        expense = _sum(db, Transaction.kind == "expense", Transaction.account_id == account.id, *ACTIVE)
        transfer_out = _sum(db, Transaction.kind == "transfer", Transaction.account_id == account.id, *ACTIVE)
        transfer_in = _sum(
            db, Transaction.kind == "transfer", Transaction.to_account_id == account.id, *ACTIVE
        )
        balance = account.opening_balance + income - expense - transfer_out + transfer_in

        result.append(
            {
                "id": account.id,
                "name": account.name,
                "kind": account.kind,
                "opening_balance": account.opening_balance,
                "balance": balance,
            }
        )

    return result


def total_balance(db: Session) -> int:
    return sum(item["balance"] for item in account_balances(db))


def summary(db: Session, period: str) -> dict:
    start, end = month_bounds(period)
    in_month = (Transaction.occurred_at >= start, Transaction.occurred_at < end)

    income = _sum(db, Transaction.kind == "income", *in_month, *ACTIVE)
    expense = _sum(db, Transaction.kind == "expense", *in_month, *ACTIVE)
    count = db.scalar(
        select(func.count(Transaction.id)).where(*in_month, *ACTIVE, Transaction.kind != "transfer")
    )

    return {
        "period": period,
        "label": period_label(period),
        "income": income,
        "expense": expense,
        "net": income - expense,
        "count": int(count or 0),
    }


def analytics(db: Session, period: str) -> dict:
    """Insight ringkas berbasis query deterministik untuk dashboard dan bot."""
    current = summary(db, period)
    previous = summary(db, shift_period(period, -1))
    start, end = month_bounds(period)
    days = max((end - start).days, 1)
    categories = category_totals(db, period, kind="expense", limit=3)
    merchants = db.execute(
        select(Transaction.merchant, func.sum(Transaction.amount))
        .where(Transaction.kind == "expense", Transaction.merchant.is_not(None),
               Transaction.occurred_at >= start, Transaction.occurred_at < end, *ACTIVE)
        .group_by(Transaction.merchant).order_by(func.sum(Transaction.amount).desc()).limit(5)
    ).all()
    highest = db.execute(
        select(Transaction.amount, Transaction.merchant, Transaction.kind)
        .where(Transaction.kind != "transfer", Transaction.occurred_at >= start,
               Transaction.occurred_at < end, *ACTIVE)
        .order_by(Transaction.amount.desc()).limit(1)
    ).first()
    active_days = db.scalar(
        select(func.count(func.distinct(func.date(Transaction.occurred_at))))
        .where(Transaction.kind != "transfer", Transaction.occurred_at >= start,
               Transaction.occurred_at < end, *ACTIVE)
    ) or 0
    account_rows = db.execute(
        select(Account.name, func.sum(Transaction.amount))
        .join(Transaction, Transaction.account_id == Account.id)
        .where(Transaction.kind == "expense", Transaction.occurred_at >= start,
               Transaction.occurred_at < end, *ACTIVE)
        .group_by(Account.id).order_by(func.sum(Transaction.amount).desc()).limit(3)
    ).all()
    savings_rate = round(current["net"] / current["income"] * 100) if current["income"] else 0
    return {
        **current,
        "previous_income": previous["income"],
        "previous_expense": previous["expense"],
        "income_change_pct": round((current["income"] - previous["income"]) / previous["income"] * 100) if previous["income"] else 0,
        "expense_change_pct": round((current["expense"] - previous["expense"]) / previous["expense"] * 100) if previous["expense"] else 0,
        "daily_average": round(current["expense"] / days),
        "top_category": categories[0] if categories else None,
        "top_merchants": [{"name": name, "total": int(total or 0)} for name, total in merchants],
        "active_days": int(active_days),
        "average_transaction": round(current["expense"] / current["count"]) if current["count"] else 0,
        "savings_rate": savings_rate,
        "highest_transaction": {"amount": int(highest[0]), "merchant": highest[1] or "Transaksi", "kind": highest[2]} if highest else None,
        "top_accounts": [{"name": name, "total": int(total or 0)} for name, total in account_rows],
    }


def range_summary(db: Session, start: datetime, end: datetime) -> dict:
    """Ringkasan pemasukan/pengeluaran untuk rentang waktu lokal yang sudah UTC."""
    income = _sum(db, Transaction.kind == "income", Transaction.occurred_at >= start, Transaction.occurred_at < end, *ACTIVE)
    expense = _sum(db, Transaction.kind == "expense", Transaction.occurred_at >= start, Transaction.occurred_at < end, *ACTIVE)
    expense_count = db.scalar(select(func.count(Transaction.id)).where(Transaction.kind == "expense", Transaction.occurred_at >= start, Transaction.occurred_at < end, *ACTIVE)) or 0
    income_count = db.scalar(select(func.count(Transaction.id)).where(Transaction.kind == "income", Transaction.occurred_at >= start, Transaction.occurred_at < end, *ACTIVE)) or 0
    return {"income": income, "expense": expense, "net": income - expense, "count": int(expense_count + income_count), "expense_count": int(expense_count), "income_count": int(income_count)}


def named_range_summary(db: Session, scope: str) -> dict:
    """Ringkasan hari/minggu/bulan berdasarkan timezone aplikasi."""
    local_now = now_local()
    today = local_now.date()
    if scope == "day":
        local_start = datetime.combine(today, datetime.min.time(), tzinfo=local_now.tzinfo)
        label = "Hari ini"
    elif scope == "week":
        local_start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time(), tzinfo=local_now.tzinfo)
        label = "Minggu ini"
    else:
        local_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = "Bulan ini"
    local_end = local_now
    data = range_summary(db, to_utc(local_start), to_utc(local_end + timedelta(seconds=1)))
    return {**data, "label": label}


def cashflow(db: Session, months: int = 6, end_period: str | None = None) -> list[dict]:
    """Pemasukan vs pengeluaran beberapa bulan terakhir untuk chart batang."""
    periods: list[dict] = []
    current = end_period or current_period()

    for offset in range(months - 1, -1, -1):
        period = shift_period(current, -offset)
        data = summary(db, period)
        periods.append(
            {
                "period": period,
                "label": period_label(period),
                "income": data["income"],
                "expense": data["expense"],
            }
        )

    # Skala untuk tinggi batang (dihitung di sini agar template tetap sederhana).
    peak = max([max(item["income"], item["expense"]) for item in periods] + [1])
    for item in periods:
        item["income_pct"] = round(item["income"] / peak * 100)
        item["expense_pct"] = round(item["expense"] / peak * 100)

    return periods


def category_totals(db: Session, period: str, kind: str = "expense", limit: int = 6) -> list[dict]:
    start, end = month_bounds(period)
    rows = db.execute(
        select(Category.name, Category.color, func.sum(Transaction.amount))
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            Transaction.kind == kind,
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
            *ACTIVE,
        )
        .group_by(Category.id)
        .order_by(func.sum(Transaction.amount).desc())
    ).all()

    total = sum(int(row[2] or 0) for row in rows) or 1
    items = [
        {
            "name": row[0],
            "color": row[1],
            "total": int(row[2] or 0),
            "pct": round(int(row[2] or 0) / total * 100),
        }
        for row in rows
    ]

    if len(items) > limit:
        head = items[: limit - 1]
        rest = items[limit - 1 :]
        head.append(
            {
                "name": "Kategori lain",
                "color": "#64748b",
                "total": sum(item["total"] for item in rest),
                "pct": sum(item["pct"] for item in rest),
            }
        )
        items = head

    return items


def budget_progress(db: Session, period: str) -> list[dict]:
    """Budget bulan ini beserta pemakaiannya per kategori."""
    start, end = month_bounds(period)
    budgets = db.scalars(
        select(Budget).where(Budget.period == period).order_by(Budget.amount.desc())
    ).all()

    result = []
    for budget in budgets:
        spent = _sum(
            db,
            Transaction.kind == "expense",
            Transaction.category_id == budget.category_id,
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
            *ACTIVE,
        )
        pct = round(spent / budget.amount * 100) if budget.amount else 0
        result.append(
            {
                "id": budget.id,
                "category_id": budget.category_id,
                "name": budget.category.name if budget.category else "-",
                "color": budget.category.color if budget.category else "#64748b",
                "amount": budget.amount,
                "spent": spent,
                "remaining": budget.amount - spent,
                "pct": pct,
                "over": spent > budget.amount,
            }
        )

    return result


def donut_segments(items: list[dict], radius: int = 40) -> list[dict]:
    """Ubah persentase kategori menjadi potongan donat SVG."""
    circumference = 2 * 3.14159265 * radius
    segments = []
    offset = 0.0

    for item in items:
        length = item["pct"] / 100 * circumference
        segments.append(
            {
                **item,
                "dash": f"{length:.2f} {circumference - length:.2f}",
                "offset": f"{-offset:.2f}",
            }
        )
        offset += length

    return segments
