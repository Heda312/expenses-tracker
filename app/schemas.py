"""Skema validasi input (Pydantic).

Dipakai untuk memvalidasi form website. Pesan error dari sini langsung
ditampilkan ke pengguna, jadi ditulis dalam bahasa Indonesia.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.dates import TZ, to_utc
from app.services.money import parse_amount


class TransactionInput(BaseModel):
    kind: Literal["expense", "income", "transfer"] = "expense"
    amount: int = Field(gt=0)
    account_id: int
    to_account_id: int | None = None
    category_id: int | None = None
    merchant: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    occurred_at: datetime

    @field_validator("amount", mode="before")
    @classmethod
    def _normalize_amount(cls, value):
        parsed = parse_amount(value)
        if not parsed or parsed <= 0:
            raise ValueError("Nominal tidak valid")
        return parsed

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _to_utc(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        return to_utc(value)

    @field_validator("merchant", "note", mode="before")
    @classmethod
    def _empty_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("to_account_id", "category_id", mode="before")
    @classmethod
    def _empty_int_to_none(cls, value):
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return None
        if isinstance(value, str):
            return int(value)
        return value


class AccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["cash", "bank", "ewallet"] = "cash"
    opening_balance: int = 0

    @field_validator("opening_balance", mode="before")
    @classmethod
    def _normalize_balance(cls, value):
        return parse_amount(value) or 0


class BudgetInput(BaseModel):
    category_id: int
    period: str = Field(min_length=7, max_length=7)
    amount: int = Field(gt=0)

    @field_validator("amount", mode="before")
    @classmethod
    def _normalize_amount(cls, value):
        parsed = parse_amount(value)
        if not parsed or parsed <= 0:
            raise ValueError("Nominal budget tidak valid")
        return parsed


class PasswordInput(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=200)
