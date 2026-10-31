"""Dashboard utama."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Transaction
from app.security import require_user
from app.services import ledger
from app.services.dates import month_bounds, shift_period, valid_period
from app.templating import templates

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    period: str | None = None,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    period = valid_period(period)
    start, end = month_bounds(period)

    data = ledger.analytics(db, period)
    balances = ledger.account_balances(db)
    expense_categories = ledger.category_totals(db, period, kind="expense", limit=6)
    cashflow = ledger.cashflow(db, months=6, end_period=period)

    recent = db.scalars(
        select(Transaction)
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
            Transaction.kind != "transfer",
        )
        .order_by(Transaction.occurred_at.desc())
        .limit(8)
    ).all()

    # Statistik sumber kategori, untuk melihat seberapa sering LLM dipakai.
    sources = {"merchant": 0, "fuzzy": 0, "rule": 0, "llm": 0, "none": 0, "manual": 0}
    for row in db.scalars(
        select(Transaction).where(
            Transaction.deleted_at.is_(None),
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
        )
    ).all():
        key = row.category_source or "manual"
        sources[key] = sources.get(key, 0) + 1

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "page_name": "dashboard",
            "period": period,
            "prev_period": shift_period(period, -1),
            "next_period": shift_period(period, 1),
            "data": data,
            "balances": balances,
            "total_balance": sum(item["balance"] for item in balances),
            "cashflow": cashflow,
            "cashflow_has_data": any(item["income"] or item["expense"] for item in cashflow),
            "categories": expense_categories,
            "donut": ledger.donut_segments(expense_categories, radius=40),
            "budgets": ledger.budget_progress(db, period)[:4],
            "recent": recent,
            "sources": sources,
        },
    )
