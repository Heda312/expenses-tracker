"""Halaman pengaturan: ganti password, hapus akun, dan info sistem."""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (
    Account,
    AuditLog,
    Budget,
    Category,
    LoginAttempt,
    Merchant,
    Transaction,
    User,
    UserSession,
)
from app.schemas import PasswordInput
from app.security import (
    COOKIE_NAME,
    check_origin,
    hash_password,
    require_user,
    verify_password,
)
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/settings")
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    source_rows = db.execute(
        select(Transaction.category_source, func.count(Transaction.id))
        .where(Transaction.deleted_at.is_(None))
        .group_by(Transaction.category_source)
    ).all()

    sources = {row[0] or "manual": int(row[1]) for row in source_rows}
    total = sum(sources.values()) or 1

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "page_name": "settings",
            "user": user,
            "sources": [
                {"name": key, "count": value, "pct": round(value / total * 100)}
                for key, value in sorted(sources.items(), key=lambda item: -item[1])
            ],
            "transaction_count": total,
            "merchant_count": int(db.scalar(select(func.count(Merchant.id))) or 0),
            "telegram_active": bool(settings.telegram_bot_token),
            "timezone": settings.timezone,
        },
    )


@router.post("/settings/password")
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    check_origin(request)

    try:
        data = PasswordInput(current_password=current_password, new_password=new_password)
    except (ValidationError, ValueError):
        return RedirectResponse("/settings?flash=invalid", status_code=303)

    if not verify_password(data.current_password, user.password_hash):
        return RedirectResponse("/settings?flash=wrong", status_code=303)

    user.password_hash = hash_password(data.new_password)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()

    response = RedirectResponse("/login?flash=password", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.post("/settings/delete-account")
def delete_account(
    request: Request,
    password: str = Form(""),
    confirm_password: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    check_origin(request)

    if not password or not confirm_password:
        return RedirectResponse("/settings?flash=missing_fields", status_code=303)

    if password != confirm_password:
        return RedirectResponse("/settings?flash=password_mismatch", status_code=303)

    if not verify_password(password, user.password_hash):
        return RedirectResponse("/settings?flash=wrong_password", status_code=303)

    # Hapus seluruh data aplikasi, lalu arahkan ke halaman daftar.
    # Urutannya penting: tabel yang mereferensikan tabel lain dihapus lebih dulu
    # supaya tidak kena FOREIGN KEY constraint.
    try:
        db.execute(delete(AuditLog))
        db.execute(delete(Budget))
        db.execute(delete(Transaction))
        db.execute(delete(Merchant))
        db.execute(delete(Account))
        db.execute(delete(Category))
        db.execute(delete(UserSession))
        db.execute(delete(LoginAttempt))
        db.execute(delete(User))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Gagal menghapus data akun")
        return RedirectResponse("/settings?flash=error", status_code=303)

    response = RedirectResponse("/register?flash=deleted", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
    
    response = RedirectResponse("/register?flash=deleted", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
