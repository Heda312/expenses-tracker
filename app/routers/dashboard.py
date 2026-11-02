"""Dashboard ringkas berbasis periode."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Transaction
from app.security import require_user
from app.services import dashboard, ledger
from app.templating import templates

router = APIRouter()


@router.get("/")
def dashboard_page(
    request: Request,
    period: str = Query("month"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    allowed = {"today", "week", "month", "last_month", "year", "custom"}
    period = period if period in allowed else "month"
    if period == "custom" and (not start or not end or start > end):
        period, start, end = "month", None, None

    summary = dashboard.dashboard_summary(db, period, start, end)
    comparison = dashboard.period_comparison(db, summary["start"], summary["end"])
    categories = ledger.category_totals_range(db, summary["start"], summary["end"], limit=8)
    budgets = ledger.budget_progress_range(db, summary["start"], summary["end"])
    insights = dashboard.auto_insights(db, summary, comparison, categories)
    active = (Transaction.status == "confirmed", Transaction.deleted_at.is_(None))
    
    # Transactions: default all-time (not filtered by period)
    transactions = db.scalars(
        select(Transaction).where(*active)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc()).limit(10)
    ).all()

    return templates.TemplateResponse(request, "dashboard.html", {
        "page_name": "dashboard", "period": period, "custom_start": start or "",
        "custom_end": end or "", "summary": summary, "comparison": comparison,
        "categories": categories, "budgets": budgets, "insights": insights,
        "top_expenses": dashboard.top_transactions(db, summary["start"], summary["end"], "expense"),
        "top_incomes": dashboard.top_transactions(db, summary["start"], summary["end"], "income"),
        "recent": transactions,
    })
