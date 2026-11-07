"""Daftar transaksi: filter, tambah, ubah, hapus.

Semua perubahan dicatat di audit_logs supaya angka yang berubah
bisa ditelusuri kapan dan dari mana.
"""

import asyncio
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account, AuditLog, Category, Transaction, utcnow
from app.schemas import TransactionInput
from app.security import check_origin, require_user
from app.services.dates import current_period, to_local, valid_period
from app.services.periods import build_period_context, resolve_period
from app.services import classify, wallet
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


def _back(period, flash: str) -> RedirectResponse:
    params = period.params()
    params["flash"] = flash
    return RedirectResponse(f"/transactions?{urlencode(params)}", status_code=303)


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
    period_type: str = Query(""),
    period: str = Query(""),
    start: str = Query(""),
    end: str = Query(""),
    account_id: str = Query(""),
    category_id: str = Query(""),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    selected = resolve_period(period_type, period, start, end)

    conditions = [Transaction.status == "confirmed", Transaction.deleted_at.is_(None)]

    if not selected.is_all:
        conditions.append(Transaction.occurred_at >= selected.start)
        conditions.append(Transaction.occurred_at < selected.end)

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

    extra_filter = {
        "account_id": str(account_filter) if account_filter else "",
        "category_id": str(category_filter) if category_filter else "",
        "q": keyword,
    }
    context = build_period_context(selected, "/transactions", extra_filter)

    pagination_params = dict(selected.params())
    pagination_params.update({key: value for key, value in extra_filter.items() if value})

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "page_name": "transactions",
            **context,
            "account_id": account_id,
            "category_id": category_id,
            "q": keyword,
            "items": items,
            "rows": [{"tx": item, "form": _form_json(item)} for item in items],
            "total": total,
            "page": page,
            "pages": pages,
            "pagination_query": urlencode(pagination_params),
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
    period_type: str = Form(""),
    period: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)
    selected = resolve_period(period_type, period, start, end)

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
        return _back(selected, "invalid")

    if data.kind == "transfer":
        if not data.to_account_id or data.to_account_id == data.account_id:
            return _back(selected, "invalid")
        data.category_id = None
    elif data.category_id is None:
        data.category_id, _ = asyncio.run(classify.classify_category(db, data.merchant, f"{data.merchant or ''} {data.note or ''}", kind=data.kind, use_llm=False))

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
    wallet.sync_balances(db)
    db.refresh(transaction)
    
    # Check budget alerts for expense (sync version for web)
    if transaction.kind == "expense" and transaction.category_id:
        from app.services.budget_alerts import send_alert_if_needed
        from app.config import settings
        if settings.telegram_bot_token and settings.telegram_allowed_chat_id:
            send_alert_if_needed(db, settings.telegram_bot_token, settings.telegram_allowed_chat_id, current_period())

    return _back(selected, "saved")


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
    period_type: str = Form(""),
    period: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)
    selected = resolve_period(period_type, period, start, end)

    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        return _back(selected, "notfound")

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
        return _back(selected, "invalid")

    if data.kind == "transfer" and (not data.to_account_id or data.to_account_id == data.account_id):
        return _back(selected, "invalid")
    if data.kind != "transfer" and data.category_id is None:
        data.category_id, _ = asyncio.run(classify.classify_category(db, data.merchant, f"{data.merchant or ''} {data.note or ''}", kind=data.kind, use_llm=False))

    before = _snapshot(transaction)

    for field, value in data.model_dump().items():
        setattr(transaction, field, value)
    if transaction.kind == "transfer":
        transaction.category_id = None
    transaction.category_source = "manual"

    # Saldo dompet selalu dihitung ulang dari transaksi setelah perubahan
    # (lihat app/services/wallet.py), jadi cache saldo ikut diperbarui.

    _audit(db, transaction, "update", before)
    db.commit()
    wallet.sync_balances(db)

    return _back(selected, "updated")


@router.post("/transactions/{transaction_id}/confirm")
def confirm_transaction(
    transaction_id: int,
    request: Request,
    period_type: str = Form(""),
    period: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)
    selected = resolve_period(period_type, period, start, end)

    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        return _back(selected, "notfound")
    if transaction.amount <= 0:
        return _back(selected, "invalid")

    before = _snapshot(transaction)
    transaction.status = "confirmed"
    _audit(db, transaction, "update", before)
    db.commit()
    wallet.sync_balances(db)
    
    # Check budget alerts after edit (if expense category changed or amount changed)
    if transaction.kind == "expense" and transaction.category_id:
        from app.services.budget_alerts import send_alert_if_needed
        from app.services.dates import current_period
        from app.config import settings
        if settings.telegram_bot_token and settings.telegram_allowed_chat_id:
            send_alert_if_needed(db, settings.telegram_bot_token, settings.telegram_allowed_chat_id, current_period())

    return _back(selected, "updated")


@router.post("/transactions/{transaction_id}/delete")
def delete_transaction(
    transaction_id: int,
    request: Request,
    period_type: str = Form(""),
    period: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)
    selected = resolve_period(period_type, period, start, end)

    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        return _back(selected, "notfound")

    before = _snapshot(transaction)
    transaction.deleted_at = utcnow()
    _audit(db, transaction, "delete", before)
    db.commit()
    wallet.sync_balances(db)
    
    # Check budget alerts after delete (if was expense)
    if transaction.kind == "expense" and transaction.category_id:
        from app.services.budget_alerts import send_alert_if_needed
        from app.services.dates import current_period
        from app.config import settings
        if settings.telegram_bot_token and settings.telegram_allowed_chat_id:
            send_alert_if_needed(db, settings.telegram_bot_token, settings.telegram_allowed_chat_id, current_period())

    return _back(selected, "deleted")


@router.post("/transactions/bulk-delete")
def bulk_delete_transactions(
    request: Request,
    tx_ids: list[int] = Form([]),
    period_type: str = Form(""),
    period: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)
    selected = resolve_period(period_type, period, start, end)

    if not tx_ids:
        return _back(selected, "no-select")

    transactions = db.scalars(
        select(Transaction).where(
            Transaction.id.in_(tx_ids),
            Transaction.deleted_at.is_(None),
        )
    ).all()
    if not transactions:
        return _back(selected, "notfound")

    # Soft delete. Saldo dompet dihitung ulang dari transaksi (exclude deleted_at)
    now = utcnow()
    for tx in transactions:
        before = _snapshot(tx)
        tx.deleted_at = now
        _audit(db, tx, "delete", before)
    db.commit()
    wallet.sync_balances(db)
    
    # Verify deletion by reloading
    remaining = db.scalars(
        select(Transaction).where(Transaction.id.in_(tx_ids))
    ).all()
    if any(t.deleted_at is None for t in remaining):
        return _back(selected, "delete-error")

    return _back(selected, "deleted")
