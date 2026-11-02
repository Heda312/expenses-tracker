"""Kategori bawaan aplikasi."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Category


def ensure_seed(db: Session) -> None:
    """Buat akun Cash default jika database kosong. Kategori dibuat oleh user."""
    # Hanya buat akun default jika belum ada
    if db.scalar(select(Account.id).limit(1)) is None:
        db.add(Account(name="Cash", kind="cash", opening_balance=0))
        db.commit()
