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
    ("Rumah Tangga", "expense", "#fb7185"),
    ("Komunikasi", "expense", "#06b6d4"),
    ("Keuangan", "expense", "#8b5cf6"),
    ("Pakaian", "expense", "#ec4899"),
    ("Perawatan Diri", "expense", "#f472b6"),
    ("Langganan", "expense", "#6366f1"),
    ("Pajak & Administrasi", "expense", "#64748b"),
    ("Donasi & Zakat", "expense", "#10b981"),
    ("Hewan Peliharaan", "expense", "#84cc16"),
    ("Anak", "expense", "#f59e0b"),
    ("Perjalanan", "expense", "#14b8a6"),
    ("Hadiah", "expense", "#e11d48"),
    ("Lainnya", "expense", "#94a3b8"),
    ("Gaji", "income", "#34d399"),
    ("Bonus", "income", "#4ade80"),
    ("Pemasukan Lain", "income", "#86efac"),
    ("Freelance", "income", "#22c55e"),
    ("Investasi", "income", "#16a34a"),
    ("Penjualan", "income", "#15803d"),
    ("Cashback", "income", "#65a30d"),
    ("Bunga", "income", "#059669"),
]

CATEGORY_NAMES = [name for name, _kind, _color in DEFAULT_CATEGORIES]


def ensure_seed(db: Session) -> None:
    """Isi kategori dan dompet awal kalau database masih kosong."""
    existing_names = set(db.scalars(select(Category.name)).all())
    for order, (name, kind, color) in enumerate(DEFAULT_CATEGORIES):
        if name not in existing_names:
            db.add(Category(name=name, kind=kind, color=color, sort_order=order))

    if db.scalar(select(Account.id).limit(1)) is None:
        db.add(Account(name="Cash", kind="cash", opening_balance=0))

    db.commit()
