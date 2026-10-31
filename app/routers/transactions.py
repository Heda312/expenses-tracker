"""Daftar transaksi: filter, tambah, ubah, hapus.

Semua perubahan dicatat di audit_logs supaya angka yang berubah
bisa ditelusuri kapan dan dari mana.
"""

import json

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account, AuditLog, Category, Transaction, utcnow
from app.schemas import TransactionInput
from app.security import check_origin, require_user
from app.services.dates import current_period, month_bounds, to_local, valid_period
from app.templating import templates

router = APIRouter()
PER_PAGE = 25


def _snapshot(transaction: Transaction) -> str:
    return json.dumps(
        {
            "kind": transaction.kind,
            "amount": transaction.amount,
            "account_id": transaction.account_id,
            "to_account_id": transaction.to_account_id,
            "category_id": transaction.category_id,
            "merchant": transaction.merchant,
            "note": transaction.note,
            "occurred_at": transaction.occurred_at.isoformat(),
            "status": transaction.status,
        },
        ensure_ascii=False,
    )


def _audit(db: Session, transaction: Transaction, action: str, before: str | None) -> None:
    db.add(
        AuditLog(
            entity="transaction",
            entity_id=transaction.id,
            action=action,
            before_json=before,
            after_json=_snapshot(transaction),
        )
    )


def _back(period: str, flash: str) -> RedirectResponse:
    target = period or current_period()
    return RedirectResponse(f"/transactions?period={target}&flash={flash}", status_code=303)


def _form_json(transaction: Transaction) -> dict:
    return {
        "id": transaction.id,
        "kind": transaction.kind,
        "amount": transaction.amount,
        "account_id": transaction.account_id,
        "to_account_id": transaction.to_account_id or "",
        "category_id": transaction.category_id or "",
        "merchant": transaction.merchant or "",
        "note": transaction.note or "",
        "occurred_at": to_local(transaction.occurred_at).strftime("%Y-%m-%dT%H:%M"),
    }


@router.get("/transactions")
def list_transactions(
    request: Request,
    period: str = Query(""),
    account_id: str = Query(""),
    category_id: str = Query(""),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    period = period.strip()
    if period != "all":
        period = valid_period(period or None)

    conditions = [Transaction.deleted_at.is_(None)]

    if period != "all":
        start, end = month_bounds(period)
        conditions.append(Transaction.occurred_at >= start)
        conditions.append(Transaction.occurred_at < end)

    account_filter = int(account_id) if account_id.isdigit() else None
    if account_filter:
        conditions.append(
            or_(Transaction.account_id == account_filter, Transaction.to_account_id == account_filter)
        )

    category_filter = int(category_id) if category_id.isdigit() else None
    if category_filter:
        conditions.append(Transaction.category_id == category_filter)

    keyword = q.strip()
    if keyword:
        like = f"%{keyword}%"
        conditions.append(or_(Transaction.merchant.ilike(like), Transaction.note.ilike(like)))

    total = int(db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, pages)

    items = db.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
    ).all()

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "page_name": "transactions",
            "period": period,
            "account_id": account_id,
            "category_id": category_id,
            "q": keyword,
            "items": items,
            "rows": [{"tx": item, "form": _form_json(item)} for item in items],
            "total": total,
            "page": page,
            "pages": pages,
            "accounts": db.scalars(select(Account).order_by(Account.archived, Account.name)).all(),
            "categories": db.scalars(select(Category).order_by(Category.sort_order, Category.name)).all(),
            "default_occurred": to_local(utcnow()).strftime("%Y-%m-%dT%H:%M"),
        },
    )


@router.get("/transactions/preview/{transaction_id}")
def preview_receipt(
    request: Request,
    transaction_id: int,
    period: str = Query(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        return RedirectResponse(f"/transactions?period={period or current_period()}&flash=notfound", status_code=303)

    period = period or current_period()
    return templates.TemplateResponse(
        request,
        "ocr_preview.html",
        {
            "page_name": "transactions",
            "item": transaction,
            "period": period,
            "accounts": db.scalars(select(Account).order_by(Account.archived, Account.name)).all(),
            "categories": db.scalars(select(Category).order_by(Category.sort_order, Category.name)).all(),
            "occurred_at_local": to_local(transaction.occurred_at).strftime("%Y-%m-%dT%H:%M"),
        },
    )


@router.post("/transactions/create")
def create_transaction(
    request: Request,
    kind: str = Form("expense"),
    amount: str = Form(""),
    account_id: str = Form(""),
    to_account_id: str = Form(""),
    category_id: str = Form(""),
    merchant: str = Form(""),
    note: str = Form(""),
    occurred_at: str = Form(""),
    period: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    try:
        data = TransactionInput(
            kind=kind,
            amount=amount,
            account_id=account_id,
            to_account_id=to_account_id,
            category_id=category_id,
            merchant=merchant,
            note=note,
            occurred_at=occurred_at,
        )
    except (ValidationError, ValueError):
        return _back(period, "invalid")

    if data.kind == "transfer":
        if not data.to_account_id or data.to_account_id == data.account_id:
            return _back(period, "invalid")
        data.category_id = None

    transaction = Transaction(
        **data.model_dump(),
        source="web",
        status="confirmed",
        category_source="manual",
    )
    db.add(transaction)
    db.flush()
    _audit(db, transaction, "create", None)
    db.commit()

    return _back(period, "saved")


@router.post("/transactions/{transaction_id}/update")
def update_transaction(
    transaction_id: int,
    request: Request,
    kind: str = Form("expense"),
    amount: str = Form(""),
    account_id: str = Form(""),
    to_account_id: str = Form(""),
    category_id: str = Form(""),
    merchant: str = Form(""),
    note: str = Form(""),
    occurred_at: str = Form(""),
    period: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        return _back(period, "notfound")

    try:
        data = TransactionInput(
            kind=kind,
            amount=amount,
            account_id=account_id,
            to_account_id=to_account_id,
            category_id=category_id,
            merchant=merchant,
            note=note,
            occurred_at=occurred_at,
        )
    except (ValidationError, ValueError):
        return _back(period, "invalid")

    if data.kind == "transfer" and (not data.to_account_id or data.to_account_id == data.account_id):
        return _back(period, "invalid")

    before = _snapshot(transaction)

    for field, value in data.model_dump().items():
        setattr(transaction, field, value)
    if transaction.kind == "transfer":
        transaction.category_id = None
    transaction.category_source = "manual"

    # Saldo dompet tidak disimpan di tabel accounts: selalu dihitung ulang
    # dari transaksi di app/services/ledger.py, jadi tidak perlu disesuaikan
    # manual saat transaksi dibuat/diubah/dihapus.

    _audit(db, transaction, "update", before)
    db.commit()

    return _back(period, "updated")


@router.post("/transactions/{transaction_id}/confirm")
def confirm_transaction(
    transaction_id: int,
    request: Request,
    period: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        return _back(period, "notfound")
    if transaction.amount <= 0:
        return _back(period, "invalid")

    before = _snapshot(transaction)
    transaction.status = "confirmed"
    _audit(db, transaction, "update", before)
    db.commit()

    return _back(period, "updated")


@router.post("/transactions/{transaction_id}/delete")
def delete_transaction(
    transaction_id: int,
    request: Request,
    period: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        return _back(period, "notfound")

    before = _snapshot(transaction)
    transaction.deleted_at = utcnow()
    _audit(db, transaction, "delete", before)
    db.commit()

    return _back(period, "deleted")


@router.post("/transactions/bulk-delete")
def bulk_delete_transactions(
    request: Request,
    tx_ids: list[int] = Form([]),
    period: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    if not tx_ids:
        return _back(period, "no-select")

    transactions = db.scalars(
        select(Transaction).where(
            Transaction.id.in_(tx_ids),
            Transaction.deleted_at.is_(None),
        )
    ).all()
    if not transactions:
        return _back(period, "notfound")

    # Hapus lunak (soft delete). Saldo dompet otomatis ikut menyesuaikan
    # karena dihitung dari transaksi yang belum dihapus.
    now = utcnow()
    for transaction in transactions:
        before = _snapshot(transaction)
        transaction.deleted_at = now
        _audit(db, transaction, "delete", before)
    db.commit()

    return _back(period, "deleted")
