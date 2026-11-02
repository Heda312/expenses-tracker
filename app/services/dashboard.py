"""Enhanced dashboard analytics service."""

from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction, Budget, Category, Account
from app.services.dates import now_local, to_utc, month_bounds, shift_period


def get_period_bounds(period_type: str, custom_start: str = None, custom_end: str = None):
    """Get start and end datetime for different period types."""
    now = now_local()
    today = now.date()
    
    if period_type == "today":
        start = datetime.combine(today, datetime.min.time(), tzinfo=now.tzinfo)
        end = datetime.combine(today, datetime.max.time(), tzinfo=now.tzinfo)
        label = "Hari ini"
    elif period_type == "week":
        start = datetime.combine(today - timedelta(days=6), datetime.min.time(), tzinfo=now.tzinfo)
        end = datetime.combine(today, datetime.max.time(), tzinfo=now.tzinfo)
        label = "7 hari terakhir"
    elif period_type == "month":
        return (*month_bounds(now.strftime("%Y-%m")), "Bulan ini")
    elif period_type == "last_month":
        prev = shift_period(now.strftime("%Y-%m"), -1)
        return (*month_bounds(prev), "Bulan lalu")
    elif period_type == "year":
        start = datetime(today.year, 1, 1, tzinfo=now.tzinfo)
        end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
        label = "Tahun ini"
    elif period_type == "custom" and custom_start and custom_end:
        start = datetime.fromisoformat(custom_start).replace(tzinfo=now.tzinfo)
        end = datetime.combine(datetime.fromisoformat(custom_end).date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
        label = f"{custom_start} - {custom_end}"
    else:
        # Default to current month
        return (*month_bounds(now.strftime("%Y-%m")), "Bulan ini")
    
    return to_utc(start), to_utc(end), label


def dashboard_summary(db: Session, period_type: str = "month", custom_start: str = None, custom_end: str = None):
    """Complete dashboard summary with all metrics."""
    start, end, period_label = get_period_bounds(period_type, custom_start, custom_end)
    
    # Active filters
    ACTIVE = (Transaction.status == "confirmed", Transaction.deleted_at.is_(None))
    
    # Income and expense in period
    income = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "income",
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end,
        *ACTIVE
    )) or 0
    
    expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "expense",
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end,
        *ACTIVE
    )) or 0
    
    # Net cashflow
    net_cashflow = income - expense
    
    # Savings rate
    savings_rate = round((net_cashflow / income) * 100) if income > 0 else None
    
    # Current balance (all time)
    accounts = db.scalars(select(Account).where(Account.archived == False)).all()
    total_balance = 0
    for acc in accounts:
        acc_income = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.kind == "income", Transaction.account_id == acc.id, *ACTIVE
        )) or 0
        acc_expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.kind == "expense", Transaction.account_id == acc.id, *ACTIVE
        )) or 0
        acc_transfer_out = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.kind == "transfer", Transaction.account_id == acc.id, *ACTIVE
        )) or 0
        acc_transfer_in = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.kind == "transfer", Transaction.to_account_id == acc.id, *ACTIVE
        )) or 0
        total_balance += acc.opening_balance + acc_income - acc_expense - acc_transfer_out + acc_transfer_in
    
    # Budget remaining
    current_period = now_local().strftime("%Y-%m")
    budgets = db.scalars(select(Budget).where(Budget.period == current_period)).all()
    total_budget = sum(b.amount for b in budgets) if budgets else 0
    budget_remaining = total_budget - expense if total_budget > 0 else None
    
    # Transaction counts
    income_count = db.scalar(select(func.count(Transaction.id)).where(
        Transaction.kind == "income", Transaction.occurred_at >= start, Transaction.occurred_at < end, *ACTIVE
    )) or 0
    expense_count = db.scalar(select(func.count(Transaction.id)).where(
        Transaction.kind == "expense", Transaction.occurred_at >= start, Transaction.occurred_at < end, *ACTIVE
    )) or 0
    
    # Daily average
    days_in_period = (end.date() - start.date()).days
    daily_average = round(expense / days_in_period) if days_in_period > 0 else 0
    
    return {
        "period_type": period_type,
        "period_label": period_label,
        "start": start,
        "end": end,
        "balance": total_balance,
        "income": income,
        "expense": expense,
        "net_cashflow": net_cashflow,
        "savings_rate": savings_rate,
        "budget_total": total_budget,
        "budget_remaining": budget_remaining,
        "income_count": income_count,
        "expense_count": expense_count,
        "daily_average": daily_average,
    }


def period_comparison(db: Session, current_start, current_end):
    """Compare with previous period."""
    ACTIVE = (Transaction.status == "confirmed", Transaction.deleted_at.is_(None))
    
    # Calculate period length
    period_length = (current_end - current_start).days
    prev_start = current_start - timedelta(days=period_length)
    prev_end = current_start
    
    # Previous period data
    prev_income = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "income", Transaction.occurred_at >= prev_start, Transaction.occurred_at < prev_end, *ACTIVE
    )) or 0
    
    prev_expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "expense", Transaction.occurred_at >= prev_start, Transaction.occurred_at < prev_end, *ACTIVE
    )) or 0
    
    # Current period data
    curr_income = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "income", Transaction.occurred_at >= current_start, Transaction.occurred_at < current_end, *ACTIVE
    )) or 0
    
    curr_expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "expense", Transaction.occurred_at >= current_start, Transaction.occurred_at < current_end, *ACTIVE
    )) or 0
    
    # Calculate changes
    income_change = round(((curr_income - prev_income) / prev_income * 100)) if prev_income > 0 else None
    expense_change = round(((curr_expense - prev_expense) / prev_expense * 100)) if prev_expense > 0 else None
    
    return {
        "prev_income": prev_income,
        "prev_expense": prev_expense,
        "income_change_pct": income_change,
        "expense_change_pct": expense_change,
    }


def top_transactions(db: Session, start, end, kind: str, limit: int = 5):
    """Get top transactions by amount."""
    ACTIVE = (Transaction.status == "confirmed", Transaction.deleted_at.is_(None))
    
    return db.scalars(
        select(Transaction)
        .where(
            Transaction.kind == kind,
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
            *ACTIVE
        )
        .order_by(Transaction.amount.desc())
        .limit(limit)
    ).all()


def auto_insights(db: Session, summary: dict, comparison: dict, categories: list):
    """Generate automatic insights."""
    insights = []
    
    # Cashflow status
    if summary["net_cashflow"] > 0:
        insights.append({
            "icon": "💚",
            "text": f"Arus kas surplus {summary['savings_rate']}%" if summary['savings_rate'] else "Arus kas positif"
        })
    elif summary["net_cashflow"] < 0:
        insights.append({
            "icon": "⚠️",
            "text": f"Arus kas defisit. Pengeluaran melebihi pemasukan."
        })
    
    # Expense trend
    if comparison["expense_change_pct"] is not None:
        change = comparison["expense_change_pct"]
        if abs(change) >= 10:
            icon = "📈" if change > 0 else "📉"
            direction = "naik" if change > 0 else "turun"
            insights.append({
                "icon": icon,
                "text": f"Pengeluaran {direction} {abs(change)}% dibanding periode sebelumnya"
            })
    
    # Top category
    if categories:
        top_cat = categories[0]
        if top_cat["pct"] >= 30:
            insights.append({
                "icon": "🎯",
                "text": f"Kategori {top_cat['name']} dominan ({top_cat['pct']}% dari pengeluaran)"
            })
    
    # Budget warning
    if summary["budget_remaining"] is not None:
        if summary["budget_remaining"] < 0:
            insights.append({
                "icon": "🚨",
                "text": f"Total anggaran terlampaui"
            })
        elif summary["budget_total"] > 0:
            used_pct = round((summary["expense"] / summary["budget_total"]) * 100)
            if used_pct >= 80:
                insights.append({
                    "icon": "⚡",
                    "text": f"Anggaran sudah terpakai {used_pct}%"
                })
    
    return insights[:4]  # Max 4 insights
