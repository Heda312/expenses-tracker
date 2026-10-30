"""Daftar transaksi: filter, tambah, ubah, hapus.

Semua perubahan dicatat di audit_logs supaya angka yang berubah
bisa ditelusuri kapan dan dari mana.
"""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Account, AuditLog, Category, Transaction, utcnow
from app.schemas import TransactionInput
from app.security import check_origin, require_user
from app.services import ingest, ocr, receipt
from app.services.dates import current_period, month_bounds, to_local, to_local_datetime, valid_period
from app.templating import templates

router = APIRouter()
PER_PAGE = 25


def _save_image(image_bytes: bytes) -> str:
    name = f"{uuid.uuid4().hex}.jpg"
    path = Path(settings.upload_dir) / name
    path.write_bytes(image_bytes)
    return f"uploads/{name}"


@router.post("/upload")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        return RedirectResponse("/transactions?flash=invalid", status_code=303)

    image_bytes = await file.read()
    try:
        lines = await asyncio.to_thread(ocr.read_lines, image_bytes)
    except ocr.OcrError as exc:
        logger.warning("OCR gagal: %s", exc)
        return RedirectResponse("/transactions?flash=invalid", status_code=303)

    data = receipt.parse_receipt(lines)
    account = _pick_account(db, data.raw_text)
    if account is None:
        return RedirectResponse("/transactions?flash=invalid", status_code=303)

    image_path = _save_image(image_bytes)
    occurred_at = to_local_datetime(data.date) if data.date else utcnow()
    category_id, category_source = await ingest.classify_category(db, data.merchant, data.raw_text)

    transaction = Transaction(
        kind="expense",
        amount=data.amount or 0,
        account_id=account.id,
        category_id=category_id,
        merchant=(data.merchant or None),
        note=None,
        occurred_at=occurred_at,
        source="web",
        status="pending",
        confidence=data.confidence,
        raw_text=data.raw_text[:4000],
        image_path=image_path,
        category_source=category_source,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    flash = "ok" if data.amount else "invalid"
    return RedirectResponse(f"/transactions?flash={flash}", status_code=303)


def _save_image(image_bytes: bytes, suffix: str = ".jpg") -> str:
    name = f"{uuid.uuid4().hex}{suffix}"
    path = Path(settings.upload_dir) / name
    path.write_bytes(image_bytes)
    return f"uploads/{name}"


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
    db.commit()


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


@router.post("/transactions/upload")
async def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
    period: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    content = await file.read()
    if not content:
        return RedirectResponse(f"/transactions?period={period or current_period()}&flash=invalid", status_code=303)

    ext = Path(file.filename or "").suffix.lower() or ".jpg"
    image_path = _save_image(content, ext)

    try:
        lines = await asyncio.to_thread(ocr.read_lines, content)
    except Exception as exc:
        print("OCR ERROR:", exc)
        return RedirectResponse(f"/transactions?period={period or current_period()}&flash=invalid", status_code=303)

    data = receipt.parse_receipt(lines)
    accounts = list(db.scalars(select(Account).where(Account.archived.is_(False))).all())
    if not accounts:
        return RedirectResponse(f"/transactions?period={period or current_period()}&flash=invalid", status_code=303)

    occurred_at = to_local_datetime(data.date) if data.date else utcnow()
    category_id, category_source = await classify.classify_category(db, data.merchant, data.raw_text, use_llm=False)

    transaction = Transaction(
        kind="expense",
        amount=data.amount or 0,
        account_id=accounts[0].id,
        category_id=category_id,
        merchant=(data.merchant or None),
        note=None,
        occurred_at=occurred_at,
        source="web",
        status="pending",
        confidence=data.confidence,
        raw_text=data.raw_text[:4000],
        image_path=image_path,
        category_source=category_source,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return RedirectResponse(f"/transactions/preview/{transaction.id}?period={period or current_period()}", status_code=303)


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
    db.commit()
    db.refresh(transaction)

    # Transfer antar dompet: saldo netral (sumber -X, tujuan +X)
    if data.kind == "transfer":
        source = db.get(Account, data.account_id)
        dest = db.get(Account, data.to_account_id)
        if source and dest:
            source.balance -= data.amount
            dest.balance += data.amount

    _audit(db, transaction, "create", None)

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

    # Update saldo saat transfer diubah
    if transaction.kind == "transfer" and data.account_id != transaction.account_id:
        old_source = db.get(Account, transaction.account_id)
        new_source = db.get(Account, data.account_id)
        if old_source and new_source:
            # Revert old source, apply new source
            old_source.balance += data.amount
            new_source.balance -= data.amount

    db.commit()
    _audit(db, transaction, "update", before)

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
    db.commit()
    _audit(db, transaction, "update", before)

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

    # Restore balance untuk transfer
    if transaction.kind == "transfer":
        source = db.get(Account, transaction.account_id)
        dest = db.get(Account, transaction.to_account_id)
        if source and dest:
            source.balance += transaction.amount
            dest.balance -= transaction.amount

    transaction.deleted_at = utcnow()
    db.commit()
    _audit(db, transaction, "delete", before)

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

    # Restore balance untuk transfer sebelum delete
    for tx_id in tx_ids:
        tx = db.get(Transaction, tx_id)
        if tx and tx.kind == "transfer":
            source = db.get(Account, tx.account_id)
            dest = db.get(Account, tx.to_account_id)
            if source and dest:
                source.balance += tx.amount
                dest.balance -= tx.amount

    # Bulk soft delete
    db.execute(
        update(Transaction)
        .where(Transaction.id.in_(tx_ids))
        .values(deleted_at=utcnow())
    )
    db.commit()

    return _back(period, "deleted")
