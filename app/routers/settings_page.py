"""Halaman pengaturan: ganti password dan info sistem."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Merchant, Transaction, UserSession
from app.schemas import PasswordInput
from app.security import (
    COOKIE_NAME,
    check_origin,
    hash_password,
    require_user,
    verify_password,
)
from app.templating import templates

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
            "llm_active": settings.llm_enabled,
            "llm_model": settings.ollama_model,
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
