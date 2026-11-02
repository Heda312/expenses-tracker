"""Dashboard utama dengan analytics lengkap."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import require_user
from app.services import dashboard, ledger
from app.templating import templates

router = APIRouter()


@router.get("/")
def dashboard_page(
    request: Request,
    period: str = Query("month"),  # today, week, month, last_month, year, custom
    start: str = Query(None),
    end: str = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    # Get summary
    summary = dashboard.dashboard_summary(db, period, start, end)
    
    # Period comparison
    comparison = dashboard.period_comparison(db, summary["start"], summary["end"])
    
    # Category breakdown
    categories = ledger.category_totals(db, summary["start"], summary["end"], kind="expense", limit=8)
    
    # Budget progress
    budgets = ledger.budget_progress_period(db, summary["start"], summary["end"])
    
    # Top transactions
    top_expenses = dashboard.top_transactions(db, summary["start"], summary["end"], "expense", 5)
    top_incomes = dashboard.top_transactions(db, summary["start"], summary["end"], "income", 5)
    
    # Recent transactions
    recent = dashboard.top_transactions(db, summary["start"], summary["end"], "expense", 10)
    
    # Auto insights
    insights = dashboard.auto_insights(db, summary, comparison, categories)
    
    # Cashflow chart data
    cashflow = ledger.cashflow_daily(db, summary["start"], summary["end"])
    
    # Budget vs actual
    budget_chart = []
    for budget in budgets:
        budget_chart.append({
            "category": budget["name"],
            "budget": budget["amount"],
            "actual": budget["spent"],
            "pct": budget["pct"]
        })
    
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "page_name": "dashboard",
            "period": period,
            "summary": summary,
            "comparison": comparison,
            "categories": categories,
            "budgets": budgets,
            "top_expenses": top_expenses,
            "top_incomes": top_incomes,
            "recent": recent,
            "insights": insights,
            "cashflow": cashflow,
            "budget_chart": budget_chart,
        },
    )
