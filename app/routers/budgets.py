"""Halaman budget per kategori."""

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Budget, Category
from app.schemas import BudgetInput
from app.security import check_origin, require_user
from app.services import ledger
from app.services.dates import shift_period, valid_period
from app.templating import templates

router = APIRouter()


@router.get("/budgets")
def budgets_page(
    request: Request,
    period: str = Query(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    period = valid_period(period or None)

    return templates.TemplateResponse(
        request,
        "budgets.html",
        {
            "page_name": "budgets",
            "period": period,
            "prev_period": shift_period(period, -1),
            "next_period": shift_period(period, 1),
            "progress": ledger.budget_progress(db, period),
            "categories": db.scalars(
                select(Category).where(Category.kind == "expense").order_by(Category.sort_order)
            ).all(),
        },
    )


@router.post("/budgets/save")
def save_budget(
    request: Request,
    category_id: str = Form(""),
    period: str = Form(""),
    amount: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)
    period = valid_period(period or None)

    try:
        data = BudgetInput(category_id=category_id, period=period, amount=amount)
    except (ValidationError, ValueError):
        return RedirectResponse(f"/budgets?period={period}&flash=invalid", status_code=303)

    existing = db.scalar(
        select(Budget).where(
            Budget.category_id == data.category_id, Budget.period == data.period
        )
    )

    if existing:
        existing.amount = data.amount
    else:
        db.add(Budget(**data.model_dump()))

    db.commit()
    return RedirectResponse(f"/budgets?period={period}&flash=saved", status_code=303)


@router.post("/budgets/{budget_id}/delete")
def delete_budget(
    budget_id: int,
    request: Request,
    period: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)
    period = valid_period(period or None)

    budget = db.get(Budget, budget_id)
    if budget is None:
        return RedirectResponse(f"/budgets?period={period}&flash=notfound", status_code=303)

    db.delete(budget)
    db.commit()

    return RedirectResponse(f"/budgets?period={period}&flash=deleted", status_code=303)
