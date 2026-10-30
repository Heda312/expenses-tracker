"""Export transaksi ke Excel."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Transaction
from app.security import require_user
from app.services.dates import format_dt, month_bounds, valid_period
from app.services import ledger
from app.services.xlsx import build_workbook

router = APIRouter()

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export.xlsx")
def export_excel(
    request: Request,
    period: str = Query(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    period = valid_period(period or None)
    start, end = month_bounds(period)

    transactions = db.scalars(
        select(Transaction)
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.status == "confirmed",
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
        )
        .order_by(Transaction.occurred_at.asc())
    ).all()

    rows = [
        {
            "date": format_dt(item.occurred_at),
            "kind": item.kind,
            "category": item.category.name if item.category else "-",
            "account": item.account.name if item.account else "-",
            "merchant": item.merchant or "-",
            "note": item.note or "-",
            "amount": item.amount,
            "source": item.source,
        }
        for item in transactions
    ]

    summary = ledger.summary(db, period)
    summary["budgets"] = ledger.budget_progress(db, period)
    by_category = ledger.category_totals(db, period, kind="expense", limit=50)

    buffer = build_workbook(rows, summary, by_category)

    filename = f"catat-{period}.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type=MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
