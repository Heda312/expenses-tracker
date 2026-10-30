"""Halaman dompet / akun."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account
from app.schemas import AccountInput
from app.security import check_origin, require_user
from app.services import ledger
from app.templating import templates

router = APIRouter()


@router.get("/accounts")
def accounts_page(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    accounts = db.scalars(select(Account).order_by(Account.archived, Account.name)).all()
    balances = {item["id"]: item["balance"] for item in ledger.account_balances(db)}

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "page_name": "accounts",
            "accounts": accounts,
            "balances": balances,
            "total_balance": sum(balances.values()),
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

    db.add(Account(**data.model_dump()))
    db.commit()
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
    db.commit()

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
    db.commit()

    flash = "archived" if account.archived else "restored"
    return RedirectResponse(f"/accounts?flash={flash}", status_code=303)
