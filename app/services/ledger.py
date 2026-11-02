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
    """Saldo tiap dompet = saldo awal + masuk - keluar - transfer keluar + transfer masuk.
    Optimized: single query untuk semua akun."""
    
    from sqlalchemy import case
    
    # Aggregate all transactions per account in one query
    income_subq = (
        select(
            Transaction.account_id,
            func.coalesce(func.sum(
                case((Transaction.kind == "income", Transaction.amount), else_=0)
            ), 0).label("income"),
            func.coalesce(func.sum(
                case((Transaction.kind == "expense", Transaction.amount), else_=0)
            ), 0).label("expense"),
            func.coalesce(func.sum(
                case((Transaction.kind == "transfer", Transaction.amount), else_=0)
            ), 0).label("transfer_out"),
        )
        .where(*ACTIVE)
        .group_by(Transaction.account_id)
        .subquery()
    )
    
    # Transfer in (to_account_id)
    transfer_in_subq = (
        select(
            Transaction.to_account_id.label("account_id"),
            func.coalesce(func.sum(Transaction.amount), 0).label("transfer_in")
        )
        .where(Transaction.kind == "transfer", *ACTIVE)
        .group_by(Transaction.to_account_id)
        .subquery()
    )
    
    # Join with accounts
    query = (
        select(
            Account.id,
            Account.name,
            Account.kind,
            Account.opening_balance,
            func.coalesce(income_subq.c.income, 0).label("income"),
            func.coalesce(income_subq.c.expense, 0).label("expense"),
            func.coalesce(income_subq.c.transfer_out, 0).label("transfer_out"),
            func.coalesce(transfer_in_subq.c.transfer_in, 0).label("transfer_in"),
        )
        .outerjoin(income_subq, Account.id == income_subq.c.account_id)
        .outerjoin(transfer_in_subq, Account.id == transfer_in_subq.c.account_id)
        .where(Account.archived.is_(False))
        .order_by(Account.name)
    )
    
    result = []
    for row in db.execute(query):
        balance = row.opening_balance + row.income - row.expense - row.transfer_out + row.transfer_in
        result.append({
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "opening_balance": row.opening_balance,
            "balance": balance,
        })
    
    return result


def total_balance(db: Session) -> int:
    return sum(item["balance"] for item in account_balances(db))


def summary(db: Session, period: str) -> dict:
    """Summary periode dengan single query untuk income & expense."""
    start, end = month_bounds(period)
    in_month = (Transaction.occurred_at >= start, Transaction.occurred_at < end)
    
    from sqlalchemy import case
    
    # Single query untuk income, expense, dan count
    result = db.execute(
        select(
            func.coalesce(func.sum(case((Transaction.kind == "income", Transaction.amount), else_=0)), 0).label("income"),
            func.coalesce(func.sum(case((Transaction.kind == "expense", Transaction.amount), else_=0)), 0).label("expense"),
            func.count(Transaction.id).label("count")
        )
        .where(*in_month, *ACTIVE, Transaction.kind != "transfer")
    ).first()
    
    income = result.income if result else 0
    expense = result.expense if result else 0
    count = result.count if result else 0

    return {
        "period": period,
        "label": period_label(period),
        "income": income,
        "expense": expense,
        "net": income - expense,
        "count": int(count),
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
    savings_rate = round(current["net"] / current["income"] * 100) if current["income"] > 0 else 0
    return {
        **current,
        "previous_income": previous["income"],
        "previous_expense": previous["expense"],
        "income_change_pct": round((current["income"] - previous["income"]) / previous["income"] * 100) if previous["income"] > 0 else 0,
        "expense_change_pct": round((current["expense"] - previous["expense"]) / previous["expense"] * 100) if previous["expense"] > 0 else 0,
        "daily_average": round(current["expense"] / days),
        "active_days": int(active_days),
        "active_daily_average": round(current["expense"] / active_days) if active_days else 0,
        "top_category": categories[0] if categories else None,
        "top_merchants": [{"name": name, "total": int(total or 0)} for name, total in merchants],
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


from app.models import category_color


def category_totals_range(db: Session, start, end, kind: str = "expense", limit: int = 6) -> list[dict]:
    """Category totals for custom datetime range."""
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
            "color": row[1] or category_color(row[0]),  # fallback to generated color
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


def category_totals(db: Session, period: str, kind: str = "expense", limit: int = 6) -> list[dict]:
    start, end = month_bounds(period)
    return category_totals_range(db, start, end, kind, limit)


def budget_progress(db: Session, period: str) -> list[dict]:
    """Budget bulan ini beserta pemakaiannya per kategori.
    Optimized: single query dengan LEFT JOIN."""
    start, end = month_bounds(period)
    
    # Subquery untuk spending per kategori
    spent_subq = (
        select(
            Transaction.category_id,
            func.coalesce(func.sum(Transaction.amount), 0).label("spent")
        )
        .where(
            Transaction.kind == "expense",
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
            *ACTIVE
        )
        .group_by(Transaction.category_id)
        .subquery()
    )
    
    # Join budget dengan category dan spending
    query = (
        select(
            Budget.id,
            Budget.category_id,
            Budget.amount,
            Category.name,
            Category.color,
            func.coalesce(spent_subq.c.spent, 0).label("spent")
        )
        .join(Category, Budget.category_id == Category.id)
        .outerjoin(spent_subq, Budget.category_id == spent_subq.c.category_id)
        .where(Budget.period == period)
        .order_by(Budget.amount.desc())
    )
    
    result = []
    for row in db.execute(query):
        pct = round(row.spent / row.amount * 100) if row.amount else 0
        result.append({
            "id": row.id,
            "category_id": row.category_id,
            "name": row.name or "-",
            "color": row.color or "#64748b",
            "amount": row.amount,
            "spent": row.spent,
            "remaining": row.amount - row.spent,
            "pct": pct,
            "over": row.spent > row.amount,
        })

    return result


def budget_progress_range(db: Session, start, end) -> list[dict]:
    """Budget progress untuk custom datetime range.
    
    Logic:
    - Jika filter <= 1 bulan: tampilkan budget bulan tersebut vs spent di periode filter
    - Jika filter > 1 bulan atau cross-month: hanya tampilkan budget bulan berjalan vs spent di periode filter
    - Spent selalu sesuai range yang dipilih, tapi budget tetap per bulan (tidak diakumulasi)
    """
    # Tentukan bulan mana yang jadi referensi budget
    # Prioritas: bulan dari start date, atau bulan saat ini jika start terlalu jauh
    start_period = start.strftime("%Y-%m")
    current_period = now_local().strftime("%Y-%m")
    
    # Hitung durasi range
    days_range = (end - start).days
    
    # Jika range <= 31 hari dan dalam 1 bulan yang sama, pakai budget bulan tersebut
    if days_range <= 31 and start.strftime("%Y-%m") == end.strftime("%Y-%m"):
        reference_period = start_period
    else:
        # Jika range lebih dari 1 bulan atau cross-month, pakai budget bulan berjalan
        reference_period = current_period
    
    # Ambil budget dari periode referensi
    budgets = db.scalars(
        select(Budget)
        .where(Budget.period == reference_period)
        .order_by(Budget.amount.desc())
    ).all()

    result = []
    for budget in budgets:
        # Spent dihitung sesuai range yang dipilih user
        spent = _sum(
            db,
            Transaction.kind == "expense",
            Transaction.category_id == budget.category_id,
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
            *ACTIVE,
        )
        
        # Persentase relatif terhadap budget bulan referensi
        pct = round(spent / budget.amount * 100) if budget.amount else 0
        
        cat = budget.category
        color = cat.color if cat else None
        result.append(
            {
                "id": budget.id,
                "category_id": budget.category_id,
                "name": cat.name if cat else "-",
                "color": color or category_color(cat.name) if cat else "#64748b",
                "amount": budget.amount,
                "spent": spent,
                "remaining": budget.amount - spent,
                "pct": pct,
                "over": spent > budget.amount,
                "reference_period": reference_period,  # Info periode budget yang dipakai
            }
        )
    
    return sorted(result, key=lambda x: x["spent"], reverse=True)


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
