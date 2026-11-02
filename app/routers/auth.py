"""Halaman login, register, dan logout."""

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
    hash_password,
)
from app.templating import templates

router = APIRouter()


@router.get("/register")
def register_form(request: Request, db: Session = Depends(get_db)):
    if resolve_session(db, request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)
    
    return templates.TemplateResponse(request, "register.html", {"flash": request.query_params.get("flash")})


@router.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    check_origin(request)
    
    username = username.strip().lower()
    
    # Validate input
    if len(username) < 3 or len(username) > 190:
        return RedirectResponse("/register?flash=invalid_username", status_code=303)
    
    if len(password) < 12 or len(password) > 200:
        return RedirectResponse("/register?flash=invalid_password", status_code=303)
    
    if password != confirm_password:
        return RedirectResponse("/register?flash=password_mismatch", status_code=303)
    
    # Check if user exists
    existing = db.scalar(select(User).where(User.username == username))
    if existing:
        return RedirectResponse("/register?flash=exists", status_code=303)
    
    # Create user
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    
    # Auto login
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


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    if resolve_session(db, request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(request, "login.html", {"flash": request.query_params.get("flash")})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    check_origin(request)

    username = username.strip().lower()
    ip = request.client.host if request.client else None

    if is_login_locked(db, username, ip):
        return RedirectResponse("/login?flash=locked", status_code=303)

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        record_login_failure(db, username, ip)
        return RedirectResponse("/login?flash=wrong", status_code=303)

    clear_login_failures(db, username)
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
