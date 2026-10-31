"""Model database.

Aturan penting yang dipakai di seluruh aplikasi:
- Semua nominal disimpan sebagai INTEGER rupiah (bukan float).
- Semua waktu disimpan dalam UTC (naive), dikonversi ke zona lokal saat ditampilkan.
- Transfer disimpan sebagai SATU baris: account_id (dari) + to_account_id (ke),
  dan tidak dihitung sebagai pemasukan/pengeluaran.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Waktu sekarang dalam UTC, tanpa timezone info (konsisten untuk SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Account(Base):
    """Dompet / sumber dana: cash, rekening bank, atau e-wallet."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20), default="cash")  # cash | bank | ewallet
    opening_balance: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    kind: Mapped[str] = mapped_column(String(10), default="expense")  # expense | income
    color: Mapped[str] = mapped_column(String(9), default="#34d399")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # expense | income | transfer
    amount: Mapped[int] = mapped_column(Integer)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    to_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)

    merchant: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    source: Mapped[str] = mapped_column(String(20), default="web")  # web | telegram
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # pending | confirmed | rejected

    # Hasil ekstraksi otomatis, dipakai untuk audit dan debugging.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Untuk mencegah duplikat saat Telegram mengirim update yang sama dua kali.
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    account: Mapped["Account"] = relationship(foreign_keys=[account_id])
    to_account: Mapped["Account | None"] = relationship(foreign_keys=[to_account_id])
    category: Mapped["Category | None"] = relationship()

    __table_args__ = (
        Index("ix_transactions_occurred_at", "occurred_at"),
        Index("ix_transactions_status", "status"),
    )


class Merchant(Base):
    """Ingatan merchant: hasil normalisasi OCR -> kategori.

    Semakin lengkap tabel ini, semakin jarang LLM dipanggil.
    """

    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(80), unique=True)  # hasil normalize_merchant()
    canonical: Mapped[str] = mapped_column(String(120))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    category: Mapped["Category | None"] = relationship()


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    period: Mapped[str] = mapped_column(String(7))  # format YYYY-MM
    amount: Mapped[int] = mapped_column(Integer)

    category: Mapped["Category"] = relationship()

    __table_args__ = (UniqueConstraint("category_id", "period", name="uq_budget_category_period"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # token acak
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship()


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    identifier: Mapped[str] = mapped_column(String(190))  # email atau ip
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_login_attempts_identifier", "identifier"),)


class AuditLog(Base):
    """Riwayat perubahan transaksi supaya angka yang berubah bisa ditelusuri."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # create | update | delete
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
