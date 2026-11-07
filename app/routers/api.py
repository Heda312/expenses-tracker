"""REST API untuk bot eksternal (Hermes).

Autentikasi memakai header:

    Authorization: Bearer <HERMES_API_TOKEN>

Kalau ``HERMES_API_TOKEN`` di .env kosong, API tetap bisa dipakai lewat sesi
login website (cookie), tapi tidak bisa diakses tanpa autentikasi.

Semua endpoint ada di bawah /api/v1 dan mengembalikan JSON.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Account, Category, Transaction, category_color, utcnow
from app.security import COOKIE_NAME, resolve_session
from app.services import cleanup, importer, ledger, wallet
from app.services.dates import TZ, to_local, to_utc
from app.services.money import parse_amount

router = APIRouter(prefix="/api/v1", tags=["hermes"])


# ---------------------------------------------------------------------------
# Autentikasi
# ---------------------------------------------------------------------------


def require_api_auth(request: Request, db: Session = Depends(get_db)) -> str:
    """Terima Bearer token Hermes atau sesi login website."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if settings.hermes_api_token and secrets.compare_digest(token, settings.hermes_api_token):
            return "hermes"
        raise HTTPException(status_code=401, detail="Token tidak valid")

    user = resolve_session(db, request.cookies.get(COOKIE_NAME))
    if user is not None:
        return f"user:{user.id}"

    raise HTTPException(
        status_code=401,
        detail="Butuh header Authorization: Bearer <token> atau login website",
    )


# ---------------------------------------------------------------------------
# Skema input JSON
# ---------------------------------------------------------------------------


def _parse_dt(value) -> datetime:
    if value in (None, ""):
        return to_utc(datetime.now(TZ))
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("Format tanggal tidak valid (pakai ISO 8601)") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return to_utc(parsed)


class TransactionCreate(BaseModel):
    kind: Literal["expense", "income", "transfer"] = "expense"
    amount: int = Field(gt=0)
    account_id: int | None = None
    account: str | None = None
    to_account_id: int | None = None
    to_account: str | None = None
    category_id: int | None = None
    category: str | None = None
    merchant: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    occurred_at: datetime | str | None = None
    status: Literal["pending", "confirmed", "rejected"] = "confirmed"
    create_missing: bool = True

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value):
        parsed = parse_amount(value)
        if not parsed or parsed <= 0:
            raise ValueError("Nominal tidak valid")
        return parsed

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _occurred(cls, value):
        return _parse_dt(value)


class TransactionUpdate(BaseModel):
    kind: Literal["expense", "income", "transfer"] | None = None
    amount: int | None = None
    account_id: int | None = None
    account: str | None = None
    to_account_id: int | None = None
    to_account: str | None = None
    category_id: int | None = None
    category: str | None = None
    merchant: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    occurred_at: datetime | str | None = None
    status: Literal["pending", "confirmed", "rejected"] | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value):
        if value in (None, ""):
            return None
        parsed = parse_amount(value)
        if not parsed or parsed <= 0:
            raise ValueError("Nominal tidak valid")
        return parsed

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _occurred(cls, value):
        if value in (None, ""):
            return None
        return _parse_dt(value)


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["cash", "bank", "ewallet"] | None = None
    opening_balance: int | str = 0

    @field_validator("opening_balance", mode="before")
    @classmethod
    def _opening(cls, value):
        return parse_amount(value) or 0


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: Literal["cash", "bank", "ewallet"] | None = None
    opening_balance: int | str | None = None
    archived: bool | None = None

    @field_validator("opening_balance", mode="before")
    @classmethod
    def _opening(cls, value):
        if value in (None, ""):
            return None
        return parse_amount(value) or 0


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["expense", "income"] = "expense"
    color: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: Literal["expense", "income"] | None = None
    color: str | None = None


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def _account_json(account: Account, balance: int | None = None) -> dict:
    data = {
        "id": account.id,
        "name": account.name,
        "kind": account.kind,
        "opening_balance": account.opening_balance,
        "archived": account.archived,
        "cached_balance": account.cached_balance,
        "balance_updated_at": account.balance_updated_at.isoformat()
        if account.balance_updated_at
        else None,
    }
    if balance is not None:
        data["balance"] = balance
    return data


def _category_json(category: Category) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "kind": category.kind,
        "color": category.color,
        "sort_order": category.sort_order,
    }


def _transaction_json(transaction: Transaction) -> dict:
    return {
        "id": transaction.id,
        "kind": transaction.kind,
        "amount": transaction.amount,
        "account_id": transaction.account_id,
        "account": transaction.account.name if transaction.account else None,
        "to_account_id": transaction.to_account_id,
        "to_account": transaction.to_account.name if transaction.to_account else None,
        "category_id": transaction.category_id,
        "category": transaction.category.name if transaction.category else None,
        "merchant": transaction.merchant,
        "note": transaction.note,
        "occurred_at": transaction.occurred_at.isoformat(),
        "occurred_at_local": to_local(transaction.occurred_at).isoformat(),
        "status": transaction.status,
        "source": transaction.source,
        "deleted_at": transaction.deleted_at.isoformat() if transaction.deleted_at else None,
        "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
        "updated_at": transaction.updated_at.isoformat() if transaction.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _resolve_account_or_create(
    db: Session, account_id: int | None, name: str | None, create_missing: bool = True
) -> Account | None:
    if account_id:
        account = db.get(Account, account_id)
        if account is None:
            raise HTTPException(404, f"Dompet id {account_id} tidak ditemukan")
        return account

    if name and name.strip():
        account = wallet.resolve_account(db, name)
        if account is not None:
            return account
        if not create_missing:
            raise HTTPException(404, f"Dompet '{name}' tidak ditemukan")
        account, _ = wallet.get_or_create_account(db, name)
        return account

    return None


def _resolve_category_or_create(
    db: Session,
    category_id: int | None,
    name: str | None,
    kind: str,
    create_missing: bool = True,
) -> Category | None:
    if category_id:
        category = db.get(Category, category_id)
        if category is None:
            raise HTTPException(404, f"Kategori id {category_id} tidak ditemukan")
        return category

    if name and name.strip():
        clean = " ".join(name.split())
        existing = db.scalar(
            select(Category).where(func.lower(Category.name) == clean.lower()).limit(1)
        )
        if existing is not None:
            return existing
        if not create_missing:
            raise HTTPException(404, f"Kategori '{name}' tidak ditemukan")
        category = Category(
            name=clean[:60],
            kind="income" if kind == "income" else "expense",
            color=category_color(clean),
        )
        db.add(category)
        db.flush()
        return category

    return None


def _sync_wallet_response(db: Session) -> list[dict]:
    return [
        {"id": item["id"], "name": item["name"], "balance": item["balance"]}
        for item in wallet.sync_balances(db)
        if not item["archived"]
    ]


# ---------------------------------------------------------------------------
# Health & ringkasan
# ---------------------------------------------------------------------------


@router.get("/health")
def api_health():
    return {"status": "ok", "app": settings.app_name, "time": utcnow().isoformat()}


@router.get("/summary")
def api_summary(db: Session = Depends(get_db), _auth=Depends(require_api_auth)):
    balances = wallet.balances(db)
    total = sum(item["balance"] for item in balances)
    return {
        "total_balance": total,
        "wallets": [
            {
                "id": item["id"],
                "name": item["name"],
                "kind": item["kind"],
                "balance": item["balance"],
                "transaction_count": item["transaction_count"],
            }
            for item in balances
        ],
        "transaction_count": int(
            db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.deleted_at.is_(None), Transaction.status == "confirmed"
                )
            )
            or 0
        ),
    }


# ---------------------------------------------------------------------------
# Dompet
# ---------------------------------------------------------------------------


@router.get("/accounts")
def api_list_accounts(
    include_archived: bool = Query(True),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    snapshot = wallet.sync_balances(db, commit=False)
    if not include_archived:
        snapshot = [item for item in snapshot if not item["archived"]]
    return {
        "accounts": [
            {
                "id": item["id"],
                "name": item["name"],
                "kind": item["kind"],
                "archived": item["archived"],
                "opening_balance": item["opening_balance"],
                "income": item["income"],
                "expense": item["expense"],
                "transfer_in": item["transfer_in"],
                "transfer_out": item["transfer_out"],
                "transaction_count": item["transaction_count"],
                "balance": item["balance"],
                "balance_updated_at": item["balance_updated_at"].isoformat()
                if item["balance_updated_at"]
                else None,
            }
            for item in snapshot
        ],
        "total_balance": sum(item["balance"] for item in snapshot if not item["archived"]),
    }


@router.post("/accounts", status_code=201)
def api_create_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    existing = wallet.resolve_account(db, payload.name)
    if existing is not None:
        raise HTTPException(409, f"Dompet '{payload.name}' sudah ada")

    account = Account(
        name=wallet.normalize_name(payload.name)[:80],
        kind=payload.kind or wallet.guess_kind(payload.name),
        opening_balance=int(payload.opening_balance or 0),
    )
    db.add(account)
    db.commit()
    wallet.sync_balances(db)
    db.refresh(account)

    balance = wallet.balances_map(db).get(account.id, 0)
    return _account_json(account, balance)


@router.get("/accounts/{account_id}")
def api_get_account(
    account_id: int,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Dompet tidak ditemukan")

    detail = next(
        (item for item in wallet.balances(db, include_archived=True) if item["id"] == account_id),
        None,
    )
    data = _account_json(account, detail["balance"] if detail else 0)
    if detail:
        data.update(
            {
                "income": detail["income"],
                "expense": detail["expense"],
                "transfer_in": detail["transfer_in"],
                "transfer_out": detail["transfer_out"],
                "transaction_count": detail["transaction_count"],
            }
        )
    return data


@router.patch("/accounts/{account_id}")
def api_update_account(
    account_id: int,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Dompet tidak ditemukan")

    if payload.name:
        account.name = wallet.normalize_name(payload.name)[:80]
    if payload.kind:
        account.kind = payload.kind
    if payload.opening_balance is not None:
        account.opening_balance = int(payload.opening_balance)
    if payload.archived is not None:
        account.archived = payload.archived

    db.commit()
    wallet.sync_balances(db)
    db.refresh(account)
    return _account_json(account, wallet.balances_map(db).get(account.id, 0))


@router.delete("/accounts/{account_id}")
def api_delete_account(
    account_id: int,
    force: bool = Query(False, description="Hapus juga transaksi yang masih aktif"),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Dompet tidak ditemukan")

    result = cleanup.delete_account(db, account_id, force=force)
    if not result.deleted:
        if result.reason == "notfound":
            raise HTTPException(404, "Dompet tidak ditemukan")
        raise HTTPException(
            409,
            f"Dompet masih punya {result.active_transactions} transaksi aktif. "
            "Hapus transaksinya dulu atau pakai ?force=true.",
        )

    wallet.sync_balances(db)
    return {
        "success": True,
        "deleted_transactions": result.purged_transactions,
        "detached_transfers": result.detached_transactions,
    }


@router.post("/accounts/sync")
def api_sync_accounts(db: Session = Depends(get_db), _auth=Depends(require_api_auth)):
    return {"success": True, "accounts": _sync_wallet_response(db)}


# ---------------------------------------------------------------------------
# Kategori
# ---------------------------------------------------------------------------


@router.get("/categories")
def api_list_categories(
    kind: str = Query("", description="expense | income"),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    query = select(Category).order_by(Category.kind, Category.sort_order, Category.name)
    if kind in ("expense", "income"):
        query = query.where(Category.kind == kind)
    return {"categories": [_category_json(item) for item in db.scalars(query).all()]}


@router.post("/categories", status_code=201)
def api_create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    clean = " ".join(payload.name.split())
    existing = db.scalar(
        select(Category).where(func.lower(Category.name) == clean.lower()).limit(1)
    )
    if existing is not None:
        raise HTTPException(409, f"Kategori '{clean}' sudah ada")

    max_order = db.scalar(select(func.max(Category.sort_order))) or 0
    category = Category(
        name=clean[:60],
        kind=payload.kind,
        color=payload.color or category_color(clean),
        sort_order=max_order + 1,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return _category_json(category)


@router.patch("/categories/{category_id}")
def api_update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Kategori tidak ditemukan")

    if payload.name:
        clean = " ".join(payload.name.split())
        duplicate = db.scalar(
            select(Category)
            .where(func.lower(Category.name) == clean.lower(), Category.id != category_id)
            .limit(1)
        )
        if duplicate is not None:
            raise HTTPException(409, f"Kategori '{clean}' sudah ada")
        category.name = clean[:60]
    if payload.kind:
        category.kind = payload.kind
    if payload.color:
        category.color = payload.color

    db.commit()
    db.refresh(category)
    return _category_json(category)


@router.delete("/categories/{category_id}")
def api_delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    result = cleanup.delete_category(db, category_id)
    if not result.deleted:
        if result.reason == "notfound":
            raise HTTPException(404, "Kategori tidak ditemukan")
        raise HTTPException(
            409,
            f"Kategori dipakai di {result.active_transactions} transaksi aktif. "
            "Ubah transaksinya dulu.",
        )

    return {
        "success": True,
        "detached_transactions": result.detached_transactions,
        "deleted_budgets": result.deleted_budgets,
    }


# ---------------------------------------------------------------------------
# Transaksi
# ---------------------------------------------------------------------------


@router.get("/transactions")
def api_list_transactions(
    account_id: int | None = Query(None),
    category_id: int | None = Query(None),
    kind: str = Query("", description="expense | income | transfer"),
    status: str = Query("", description="pending | confirmed | rejected"),
    q: str = Query(""),
    start: str = Query("", description="YYYY-MM-DD (lokal)"),
    end: str = Query("", description="YYYY-MM-DD (lokal)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    conditions = []
    if not include_deleted:
        conditions.append(Transaction.deleted_at.is_(None))
    if account_id:
        conditions.append(
            or_(Transaction.account_id == account_id, Transaction.to_account_id == account_id)
        )
    if category_id:
        conditions.append(Transaction.category_id == category_id)
    if kind in ("expense", "income", "transfer"):
        conditions.append(Transaction.kind == kind)
    if status in ("pending", "confirmed", "rejected"):
        conditions.append(Transaction.status == status)
    if q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                Transaction.merchant.ilike(pattern),
                Transaction.note.ilike(pattern),
            )
        )
    if start:
        conditions.append(Transaction.occurred_at >= _parse_dt(start))
    if end:
        conditions.append(Transaction.occurred_at < _parse_dt(f"{end} 23:59:59"))

    total = int(
        db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0
    )
    items = db.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "transactions": [_transaction_json(item) for item in items],
    }


@router.post("/transactions", status_code=201)
def api_create_transaction(
    payload: TransactionCreate,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    account = _resolve_account_or_create(
        db, payload.account_id, payload.account, payload.create_missing
    )
    if account is None:
        account = wallet.ensure_default_account(db)

    to_account = None
    if payload.kind == "transfer":
        to_account = _resolve_account_or_create(
            db, payload.to_account_id, payload.to_account, payload.create_missing
        )
        if to_account is None or to_account.id == account.id:
            raise HTTPException(400, "Transfer butuh dompet tujuan yang berbeda")

    category = None
    if payload.kind != "transfer":
        category = _resolve_category_or_create(
            db, payload.category_id, payload.category, payload.kind, payload.create_missing
        )

    transaction = Transaction(
        kind=payload.kind,
        amount=payload.amount,
        account_id=account.id,
        to_account_id=to_account.id if to_account else None,
        category_id=category.id if category else None,
        merchant=payload.merchant,
        note=payload.note,
        occurred_at=payload.occurred_at,
        source="hermes",
        status=payload.status,
        category_source="api" if category else None,
    )
    db.add(transaction)
    db.commit()
    wallet.sync_balances(db)
    db.refresh(transaction)
    return _transaction_json(transaction)


@router.get("/transactions/{transaction_id}")
def api_get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(404, "Transaksi tidak ditemukan")
    return _transaction_json(transaction)


@router.patch("/transactions/{transaction_id}")
def api_update_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        raise HTTPException(404, "Transaksi tidak ditemukan")

    data = payload.model_dump(exclude_unset=True)

    if "kind" in data and data["kind"]:
        transaction.kind = data["kind"]
    if data.get("amount"):
        transaction.amount = data["amount"]
    if "merchant" in data:
        transaction.merchant = data["merchant"]
    if "note" in data:
        transaction.note = data["note"]
    if data.get("occurred_at"):
        transaction.occurred_at = data["occurred_at"]
    if data.get("status"):
        transaction.status = data["status"]

    if data.get("account_id") or data.get("account"):
        account = _resolve_account_or_create(db, data.get("account_id"), data.get("account"))
        if account is not None:
            transaction.account_id = account.id

    if transaction.kind == "transfer":
        if data.get("to_account_id") or data.get("to_account"):
            to_account = _resolve_account_or_create(
                db, data.get("to_account_id"), data.get("to_account")
            )
            if to_account is not None:
                transaction.to_account_id = to_account.id
        if not transaction.to_account_id or transaction.to_account_id == transaction.account_id:
            raise HTTPException(400, "Transfer butuh dompet tujuan yang berbeda")
        transaction.category_id = None
    else:
        if data.get("category_id") or data.get("category"):
            category = _resolve_category_or_create(
                db,
                data.get("category_id"),
                data.get("category"),
                transaction.kind,
            )
            if category is not None:
                transaction.category_id = category.id
        transaction.to_account_id = None

    db.commit()
    wallet.sync_balances(db)
    db.refresh(transaction)
    return _transaction_json(transaction)


@router.delete("/transactions/{transaction_id}")
def api_delete_transaction(
    transaction_id: int,
    hard: bool = Query(False, description="Hapus permanen dari database"),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(404, "Transaksi tidak ditemukan")

    if hard:
        db.delete(transaction)
    else:
        transaction.deleted_at = utcnow()
        transaction.status = "rejected"

    db.commit()
    wallet.sync_balances(db)
    return {"success": True, "hard": hard, "id": transaction_id}


# ---------------------------------------------------------------------------
# Budget & import
# ---------------------------------------------------------------------------


@router.get("/budgets")
def api_list_budgets(
    period: str = Query("", description="YYYY-MM"),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    from app.services.dates import current_period, valid_period

    key = valid_period(period or current_period())
    items = ledger.budget_progress(db, key)
    return {"period": key, "budgets": items}


@router.post("/import/csv", status_code=201)
async def api_import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    """Import CSV; dompet yang disebut di file dibuat otomatis dan disinkronkan."""
    if not importer.is_csv_filename(file.filename or ""):
        raise HTTPException(400, "File harus CSV")

    content = await file.read()
    result = importer.import_csv(db, content, source="hermes_import")
    if result.imported == 0:
        raise HTTPException(400, "; ".join(result.messages) or "Import gagal")

    payload = result.to_dict()
    payload["total_balance"] = wallet.total_balance(db)
    return payload


@router.post("/import/csv/text", status_code=201)
def api_import_csv_text(
    body: dict,
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    """Import CSV dari body JSON: {"csv": "..."} (praktis untuk bot)."""
    text = (body or {}).get("csv") or ""
    if not text.strip():
        raise HTTPException(400, "Field 'csv' wajib diisi")

    result = importer.import_csv(db, text, source="hermes_import")
    if result.imported == 0:
        raise HTTPException(400, "; ".join(result.messages) or "Import gagal")

    payload = result.to_dict()
    payload["total_balance"] = wallet.total_balance(db)
    return payload


@router.get("/export/transactions")
def api_export_transactions(
    account_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _auth=Depends(require_api_auth),
):
    conditions = [Transaction.deleted_at.is_(None), Transaction.status == "confirmed"]
    if account_id:
        conditions.append(
            or_(Transaction.account_id == account_id, Transaction.to_account_id == account_id)
        )

    items = db.scalars(
        select(Transaction).where(*conditions).order_by(Transaction.occurred_at.asc())
    ).all()

    return {
        "count": len(items),
        "transactions": [_transaction_json(item) for item in items],
        "wallets": _sync_wallet_response(db),
    }


@router.get("/openapi.json", include_in_schema=False)
def api_openapi_hint():
    return JSONResponse(
        {
            "hint": "Dokumentasi lengkap ada di /docs",
            "auth": "Authorization: Bearer <HERMES_API_TOKEN>",
        }
    )
