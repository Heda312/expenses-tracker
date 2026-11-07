"""Enhanced analytics service dengan insight yang mudah dipahami."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction, Budget, Category
from app.services import wallet
from app.services.dates import month_bounds, shift_period, now_local
from app.services.money import format_idr


def financial_health_score(db: Session, period: str) -> dict:
    """Skor kesehatan keuangan 0-100 dengan breakdown."""
    start, end = month_bounds(period)
    
    # Get data
    income = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "income",
        Transaction.status == "confirmed",
        Transaction.deleted_at.is_(None),
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end
    )) or 0
    
    expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "expense",
        Transaction.status == "confirmed",
        Transaction.deleted_at.is_(None),
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end
    )) or 0
    
    # Budget discipline
    budgets = db.scalars(select(Budget).where(Budget.period == period)).all()
    budget_score = 0
    if budgets:
        over_budget = sum(1 for b in budgets if b.spent > b.amount) if hasattr(budgets[0], 'spent') else 0
        budget_score = max(0, 100 - (over_budget / len(budgets) * 100))
    else:
        budget_score = 50  # Neutral if no budget set
    
    # Savings rate
    savings_rate = ((income - expense) / income * 100) if income > 0 else 0
    savings_score = min(100, max(0, savings_rate * 2))  # 50% savings = 100 score
    
    # Income stability (has income this month)
    income_score = 100 if income > 0 else 0
    
    # Expense control (not spending more than earning)
    control_score = 100 if expense <= income else max(0, 100 - ((expense - income) / income * 100))
    
    # Overall score (weighted average)
    overall = (
        budget_score * 0.3 +
        savings_score * 0.3 +
        income_score * 0.2 +
        control_score * 0.2
    )
    
    # Grade
    if overall >= 80:
        grade = "Sangat Baik"
        color = "green"
        emoji = "💚"
    elif overall >= 60:
        grade = "Baik"
        color = "blue"
        emoji = "💙"
    elif overall >= 40:
        grade = "Cukup"
        color = "yellow"
        emoji = "💛"
    else:
        grade = "Perlu Perbaikan"
        color = "red"
        emoji = "❤️"
    
    return {
        "score": round(overall),
        "grade": grade,
        "color": color,
        "emoji": emoji,
        "breakdown": {
            "budget_discipline": round(budget_score),
            "savings_ability": round(savings_score),
            "income_health": round(income_score),
            "expense_control": round(control_score),
        }
    }


def spending_insights(db: Session, period: str) -> list[dict]:
    """Insight otomatis tentang pola spending."""
    start, end = month_bounds(period)
    prev_period = shift_period(period, -1)
    prev_start, prev_end = month_bounds(prev_period)
    
    insights = []
    
    # Current vs previous month
    current_expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "expense",
        Transaction.status == "confirmed",
        Transaction.deleted_at.is_(None),
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end
    )) or 0
    
    prev_expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "expense",
        Transaction.status == "confirmed",
        Transaction.deleted_at.is_(None),
        Transaction.occurred_at >= prev_start,
        Transaction.occurred_at < prev_end
    )) or 0
    
    if prev_expense > 0:
        change_pct = ((current_expense - prev_expense) / prev_expense * 100)
        if abs(change_pct) >= 20:
            insights.append({
                "type": "trend",
                "icon": "📊",
                "title": f"Pengeluaran {'naik' if change_pct > 0 else 'turun'} {abs(round(change_pct))}%",
                "text": f"Dari bulan lalu {format_idr(prev_expense)} menjadi {format_idr(current_expense)}",
                "color": "red" if change_pct > 0 else "green"
            })
    
    # Biggest category
    top_cat = db.execute(
        select(Category.name, func.sum(Transaction.amount).label('total'))
        .join(Transaction)
        .where(
            Transaction.kind == "expense",
            Transaction.status == "confirmed",
            Transaction.deleted_at.is_(None),
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end
        )
        .group_by(Category.id)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(1)
    ).first()
    
    if top_cat and current_expense > 0:
        pct = round((top_cat.total / current_expense) * 100)
        if pct >= 30:
            insights.append({
                "type": "category",
                "icon": "🎯",
                "title": f"{top_cat.name} dominan ({pct}%)",
                "text": f"Total {format_idr(top_cat.total)} dari pengeluaran bulan ini",
                "color": "blue"
            })
    
    # Budget warnings
    budgets = db.execute(
        select(Budget, Category.name)
        .join(Category)
        .where(Budget.period == period)
    ).all()
    
    for budget, cat_name in budgets:
        spent = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.kind == "expense",
            Transaction.category_id == budget.category_id,
            Transaction.status == "confirmed",
            Transaction.deleted_at.is_(None),
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end
        )) or 0
        
        pct = round((spent / budget.amount) * 100) if budget.amount > 0 else 0
        
        if spent > budget.amount:
            insights.append({
                "type": "budget",
                "icon": "⚠️",
                "title": f"Budget {cat_name} terlampaui",
                "text": f"Sudah {format_idr(spent)} dari target {format_idr(budget.amount)}",
                "color": "red"
            })
        elif pct >= 90:
            insights.append({
                "type": "budget",
                "icon": "⚡",
                "title": f"Budget {cat_name} hampir habis",
                "text": f"Tersisa {format_idr(budget.amount - spent)} dari {format_idr(budget.amount)}",
                "color": "yellow"
            })
    
    # Daily average check
    days_passed = (now_local().date() - start.date()).days + 1
    if days_passed > 0 and current_expense > 0:
        daily_avg = current_expense / days_passed
        days_in_month = (end.date() - start.date()).days
        projected = daily_avg * days_in_month
        
        if projected > current_expense * 1.3:
            insights.append({
                "type": "projection",
                "icon": "📈",
                "title": "Proyeksi pengeluaran tinggi",
                "text": f"Dengan pola saat ini, diperkirakan {format_idr(round(projected))} akhir bulan",
                "color": "yellow"
            })
    
    return insights[:5]  # Max 5 insights


def simple_summary(db: Session, period: str) -> dict:
    """Ringkasan sederhana untuk dashboard."""
    start, end = month_bounds(period)
    
    income = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "income",
        Transaction.status == "confirmed",
        Transaction.deleted_at.is_(None),
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end
    )) or 0
    
    expense = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.kind == "expense",
        Transaction.status == "confirmed",
        Transaction.deleted_at.is_(None),
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end
    )) or 0
    
    net = income - expense

    # Saldo dompet selalu dihitung dari transaksi (lihat app/services/wallet.py)
    total_balance = wallet.total_balance(db)
    
    return {
        "income": income,
        "expense": expense,
        "net": net,
        "balance": total_balance,
        "savings_rate": round((net / income * 100)) if income > 0 else None
    }
