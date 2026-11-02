"""Dashboard analitik yang mudah dipahami."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import require_user
from app.services import analytics, ledger
from app.services.dates import valid_period, shift_period
from app.templating import templates

router = APIRouter()


@router.get("/analytics")
def analytics_page(
    request: Request,
    period: str | None = None,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    period = valid_period(period)
    
    # Get analytics data
    health = analytics.financial_health_score(db, period)
    insights = analytics.spending_insights(db, period)
    summary = analytics.simple_summary(db, period)
    
    # Category breakdown
    categories = ledger.category_totals(db, period, kind="expense", limit=8)
    
    # Budget progress
    budgets = ledger.budget_progress(db, period)
    
    # Cashflow trend
    cashflow = ledger.cashflow(db, months=6, end_period=period)
    
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "page_name": "analytics",
            "period": period,
            "prev_period": shift_period(period, -1),
            "next_period": shift_period(period, 1),
            "health": health,
            "insights": insights,
            "summary": summary,
            "categories": categories,
            "budgets": budgets,
            "cashflow": cashflow,
        },
    )
