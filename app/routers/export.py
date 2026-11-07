"""Export transaksi ke Excel / CSV.

Export hanya berisi transaksi. Dompet dan kategori TIDAK diekspor terpisah:
saat file di-import ulang, dompet & kategori dibuat otomatis dari data
transaksi. Jenis dompet (tunai/bank/e-wallet) dan jam transaksi ikut ditulis
supaya tidak hilang saat round-trip.
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Transaction
from app.security import require_user
from app.services import ledger, wallet
from app.services.dates import month_bounds, to_local, valid_period
from app.services.export_formats import build_transaction_csv
from app.services.xlsx import build_workbook

router = APIRouter()

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


def _transaction_rows(transactions: list[Transaction], balances: dict[int, int]) -> list[dict]:
    """Ubah transaksi menjadi baris siap export."""
    rows = []
    for item in transactions:
        local_dt = to_local(item.occurred_at)
        rows.append(
            {
                "id": item.id,
                "date": local_dt.strftime("%Y-%m-%d"),
                "time": local_dt.strftime("%H:%M:%S"),
                "kind": item.kind,
                "amount": item.amount,
                "category": item.category.name if item.category else "",
                "account": item.account.name if item.account else "",
                "account_kind": item.account.kind if item.account else "",
                "to_account": item.to_account.name if item.to_account else "",
                "merchant": item.merchant or "",
                "note": item.note or "",
                "status": item.status,
                "source": item.source,
                # Saldo dompet setelah transaksi ini (kronologis), untuk laporan.
                "balance": balances.get(item.account_id, 0),
            }
        )
    return rows


def _fetch(db: Session, period: str) -> list[Transaction]:
    start, end = month_bounds(period)
    return list(
        db.scalars(
            select(Transaction)
            .options(
                joinedload(Transaction.category),
                joinedload(Transaction.account),
                joinedload(Transaction.to_account),
            )
            .where(
                Transaction.deleted_at.is_(None),
                Transaction.status == "confirmed",
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
            )
            .order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
        ).all()
    )


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content.encode("utf-8-sig"),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export.xlsx")
def export_excel(
    request: Request,
    period: str = Query(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    period = valid_period(period or None)
    transactions = _fetch(db, period)
    rows = _transaction_rows(transactions, wallet.balances_map(db))

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


@router.get("/export/transaksi.csv")
def export_transactions_csv(
    period: str = Query(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    """CSV transaksi saja — dompet & kategori terbentuk otomatis saat import."""
    period = valid_period(period or None)
    transactions = _fetch(db, period)
    rows = _transaction_rows(transactions, wallet.balances_map(db))
    content = build_transaction_csv(rows).getvalue()
    return _csv_response(content, f"catat-transaksi-{period}.csv")
