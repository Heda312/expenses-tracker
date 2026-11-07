"""Halaman dompet / akun.

Saldo dompet bersifat dinamis: selalu dihitung dari transaksi, bukan nilai
tetap saat dompet dibuat. Lihat app/services/wallet.py.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account
from app.schemas import AccountInput
from app.security import check_origin, require_user
from app.services import cleanup, wallet
from app.templating import templates

router = APIRouter()


@router.get("/accounts")
def accounts_page(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    snapshot = wallet.sync_balances(db, commit=False)
    accounts = db.scalars(select(Account).order_by(Account.archived, Account.name)).all()
    balances = {item["id"]: item for item in snapshot}
    details = {item["id"]: item for item in snapshot}

    # Jumlah transaksi aktif per dompet, untuk menjelaskan kenapa dompet
    # belum bisa langsung dihapus (dan apa akibatnya kalau dipaksa).
    active_counts = {
        account.id: cleanup.count_active_account_transactions(db, account.id)
        for account in accounts
    }

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "page_name": "accounts",
            "accounts": accounts,
            "balances": {key: value["balance"] for key, value in balances.items()},
            "details": details,
            "active_counts": active_counts,
            "total_balance": sum(item["balance"] for item in snapshot if not item["archived"]),
        },
    )


@router.post("/accounts/create")
def create_account(
    request: Request,
    name: str = Form(""),
    kind: str = Form("cash"),
    opening_balance: str = Form("0"),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    try:
        data = AccountInput(name=name, kind=kind, opening_balance=opening_balance)
    except (ValidationError, ValueError):
        return RedirectResponse("/accounts?flash=invalid", status_code=303)

    account, _created = wallet.get_or_create_account(
        db,
        data.name,
        kind=data.kind,
        opening_balance=data.opening_balance,
    )
    if data.opening_balance:
        account.opening_balance = data.opening_balance
    wallet.sync_balances(db)

    return RedirectResponse("/accounts?flash=saved", status_code=303)



@router.post("/accounts/{account_id}/update")
def update_account(
    account_id: int,
    request: Request,
    name: str = Form(""),
    kind: str = Form("cash"),
    opening_balance: str = Form("0"),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    account = db.get(Account, account_id)
    if account is None:
        return RedirectResponse("/accounts?flash=notfound", status_code=303)

    try:
        data = AccountInput(name=name, kind=kind, opening_balance=opening_balance)
    except (ValidationError, ValueError):
        return RedirectResponse("/accounts?flash=invalid", status_code=303)

    account.name = data.name
    account.kind = data.kind
    account.opening_balance = data.opening_balance
    wallet.sync_balances(db)

    return RedirectResponse("/accounts?flash=updated", status_code=303)


@router.post("/accounts/{account_id}/archive")
def toggle_archive(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    account = db.get(Account, account_id)
    if account is None:
        return RedirectResponse("/accounts?flash=notfound", status_code=303)

    account.archived = not account.archived
    wallet.sync_balances(db)

    flash = "archived" if account.archived else "restored"
    return RedirectResponse(f"/accounts?flash={flash}", status_code=303)


@router.post("/accounts/{account_id}/delete")
def delete_account(
    account_id: int,
    request: Request,
    force: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    check_origin(request)

    account = db.get(Account, account_id)
    if account is None:
        return RedirectResponse("/accounts?flash=notfound", status_code=303)

    result = cleanup.delete_account(db, account_id, force=bool(force))
    if not result.deleted:
        if result.reason == "notfound":
            return RedirectResponse("/accounts?flash=notfound", status_code=303)
        return RedirectResponse("/accounts?flash=has_transactions", status_code=303)

    wallet.sync_balances(db)
    return RedirectResponse("/accounts?flash=deleted", status_code=303)


@router.post("/accounts/sync")
def sync_wallets(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    """Hitung ulang saldo semua dompet dari transaksi."""
    check_origin(request)
    wallet.sync_balances(db)
    return RedirectResponse("/accounts?flash=synced", status_code=303)
