"""Keamanan: hash password, sesi login, dan pembatasan percobaan login."""

import secrets
from datetime import timedelta
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import LoginAttempt, User, UserSession, utcnow

COOKIE_NAME = "sid"

_hasher = PasswordHasher()


class RedirectToLogin(Exception):
    """Dilempar saat pengguna belum login, ditangani di main.py."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def create_session(db: Session, user: User, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            id=token,
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=settings.session_days),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:255],
        )
    )
    db.commit()
    return token


def resolve_session(db: Session, token: str | None) -> User | None:
    if not token:
        return None

    session = db.get(UserSession, token)
    if session is None:
        return None

    if session.expires_at < utcnow():
        db.delete(session)
        db.commit()
        return None

    return session.user


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.id == token))
        db.commit()


# ---------------------------------------------------------------------------
# Pembatasan percobaan login
# ---------------------------------------------------------------------------


def _count_attempts(db: Session, identifier: str) -> int:
    since = utcnow() - timedelta(minutes=settings.login_lock_minutes)
    return int(
        db.scalar(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.identifier == identifier,
                LoginAttempt.created_at >= since,
            )
        )
        or 0
    )


def is_login_locked(db: Session, email: str, ip: str | None) -> bool:
    return _count_attempts(db, f"email:{email.lower()}") >= settings.login_max_attempts or (
        ip is not None and _count_attempts(db, f"ip:{ip}") >= settings.login_max_attempts
    )


def record_login_failure(db: Session, email: str, ip: str | None) -> None:
    db.add(LoginAttempt(identifier=f"email:{email.lower()}"))
    if ip:
        db.add(LoginAttempt(identifier=f"ip:{ip}"))
    db.commit()


def clear_login_failures(db: Session, email: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.identifier == f"email:{email.lower()}"))
    db.commit()


# ---------------------------------------------------------------------------
# Dependency FastAPI
# ---------------------------------------------------------------------------


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = resolve_session(db, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise RedirectToLogin()
    return user


def check_origin(request: Request) -> None:
    """Cegah CSRF sederhana: origin/referer harus sama dengan host kita."""
    # Skip check untuk localhost development
    if request.url.hostname in ("localhost", "127.0.0.1"):
        return
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return
    if urlparse(origin).hostname != request.url.hostname:
        raise HTTPException(status_code=400, detail="Origin tidak valid")
