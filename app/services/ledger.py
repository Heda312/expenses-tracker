"""Perhitungan saldo, ringkasan bulanan, budget, dan data chart."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Budget, Category, Transaction
from app.services.dates import current_period, month_bounds, period_label, shift_period

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
