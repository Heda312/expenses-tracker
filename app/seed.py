"""Kategori bawaan aplikasi."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Category

# (nama, jenis, warna)
DEFAULT_CATEGORIES = [
    ("Makan & Minum", "expense", "#f97316"),
    ("Transportasi", "expense", "#38bdf8"),
    ("Belanja", "expense", "#a78bfa"),
    ("Tagihan", "expense", "#f43f5e"),
    ("Kesehatan", "expense", "#2dd4bf"),
    ("Hiburan", "expense", "#eab308"),
    ("Pendidikan", "expense", "#60a5fa"),
    ("Lainnya", "expense", "#94a3b8"),
    ("Gaji", "income", "#34d399"),
    ("Bonus", "income", "#4ade80"),
    ("Pemasukan Lain", "income", "#86efac"),
]

CATEGORY_NAMES = [name for name, _kind, _color in DEFAULT_CATEGORIES]


def ensure_seed(db: Session) -> None:
    """Isi kategori dan dompet awal kalau database masih kosong."""
    existing = db.scalar(select(Category.id).limit(1))
    if existing is None:
        for order, (name, kind, color) in enumerate(DEFAULT_CATEGORIES):
            db.add(Category(name=name, kind=kind, color=color, sort_order=order))

    if db.scalar(select(Account.id).limit(1)) is None:
        db.add(Account(name="Cash", kind="cash", opening_balance=0))

    db.commit()
