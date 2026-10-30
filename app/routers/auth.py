"""Halaman login dan logout."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.security import (
    COOKIE_NAME,
    check_origin,
    clear_login_failures,
    create_session,
    destroy_session,
    is_login_locked,
    record_login_failure,
    resolve_session,
    verify_password,
)
from app.templating import templates

router = APIRouter()


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    if resolve_session(db, request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(request, "login.html", {"email": ""})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    check_origin(request)

    email = email.strip().lower()
    ip = request.client.host if request.client else None

    if is_login_locked(db, email, ip):
        return RedirectResponse("/login?flash=locked", status_code=303)

    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        record_login_failure(db, email, ip)
        return RedirectResponse("/login?flash=wrong", status_code=303)

    clear_login_failures(db, email)
    token = create_session(db, user, request)

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    destroy_session(db, request.cookies.get(COOKIE_NAME))

    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
