"""Import transaksi dari CSV.

Aturan penting:
- Kolom "Dompet" di file otomatis dipakai untuk membuat dompet baru kalau
  belum ada, lalu transaksi langsung dihubungkan ke dompet tersebut.
- Setelah import selesai, saldo semua dompet dihitung ulang dari transaksi
  (lihat app/services/wallet.py), jadi saldo dompet langsung sinkron.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction
from app.services import wallet
from app.services.dates import TZ, to_utc
from app.services.money import parse_amount

DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
)

TIME_FORMATS = ("%H:%M:%S", "%H:%M", "%H.%M")

# Urutan penting:
# - "Jenis Dompet" harus dikenali sebelum "Dompet" (keduanya memuat "dompet").
# - "Dompet Tujuan" harus dicek sebelum "Dompet".
# - "Jenis" (transaksi) tidak boleh tertukar dengan "Jenis Dompet".
# - "Waktu" (jam) dipisah dari "Tanggal" supaya jam tidak hilang.
COLUMN_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("to_account", ("dompet tujuan", "ke dompet", "tujuan transfer", "to account", "to_account")),
    ("account_kind", ("jenis dompet", "tipe dompet", "wallet type", "account kind", "account_kind")),
    ("date", ("tanggal", "tgl", "date", "datetime")),
    ("time", ("waktu", "jam", "time", "pukul")),
    ("kind", ("jenis transaksi", "jenis", "tipe", "type", "kind", "debit/kredit", "dk")),
    ("amount", ("nominal", "amount", "jumlah", "total", "nilai")),
    ("category", ("kategori", "category", "cat")),
    ("merchant", ("merchant", "toko", "tempat", "keterangan", "deskripsi", "description")),
    ("account", ("dompet", "wallet", "account", "akun", "sumber dana", "rekening")),
)

INCOME_WORDS = ("income", "pemasukan", "masuk", "kredit", "credit", "cr", "in")
EXPENSE_WORDS = ("expense", "pengeluaran", "keluar", "debit", "dr", "out")
TRANSFER_WORDS = ("transfer", "pindah dana", "pindah")

# Terjemahan jenis dompet dari file import -> nilai internal.
ACCOUNT_KIND_ALIASES = {
    "cash": "cash",
    "tunai": "cash",
    "uang tunai": "cash",
    "bank": "bank",
    "rekening": "bank",
    "rekening bank": "bank",
    "tabungan": "bank",
    "ewallet": "ewallet",
    "e-wallet": "ewallet",
    "e wallet": "ewallet",
    "dompet digital": "ewallet",
    "digital": "ewallet",
}


@dataclass
class ImportResult:
    imported: int = 0
    errors: int = 0
    accounts_created: list[str] = field(default_factory=list)
    categories_created: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    wallets: list[dict] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{self.imported} transaksi diimport"]
        if self.errors:
            parts.append(f"{self.errors} baris dilewati")
        if self.accounts_created:
            parts.append(f"{len(self.accounts_created)} dompet baru")
        return ", ".join(parts)

    def to_dict(self) -> dict:
        return {
            "success": self.errors == 0 or self.imported > 0,
            "imported": self.imported,
            "errors": self.errors,
            "accounts_created": self.accounts_created,
            "categories_created": self.categories_created,
            "messages": self.messages,
            "wallets": self.wallets,
        }


def _detect_columns(header: list[str]) -> dict[str, int]:
    """Petakan header CSV ke field internal.

    Tiga tahap supaya tidak salah tangkap:
    1. Cocokkan nama kolom yang persis sama dengan hint.
    2. Cocokkan substring, dengan pengecualian antar-kolom yang mirip.
    3. Terakhir, kolom "Dompet" saja (tanpa "Jenis"/"Tujuan").
    """
    columns: dict[str, int] = {}
    normalized = [raw.strip().lower() for raw in header]

    def blocked(key: str, name: str) -> bool:
        """True kalau kolom `name` jelas bukan untuk field `key`."""
        if key == "kind":
            # "Jenis Dompet" adalah jenis dompet, bukan jenis transaksi.
            return "dompet" in name
        if key == "account":
            # "Dompet Tujuan" bukan dompet asal.
            return "tujuan" in name or "asal" in name
        if key == "account_kind":
            return "dompet" not in name
        if key == "to_account":
            return "tujuan" not in name and "ke dompet" not in name
        return False

    # Tahap 1: exact match
    for key, hints in COLUMN_HINTS:
        if key in columns:
            continue
        for index, name in enumerate(normalized):
            if name and not blocked(key, name) and any(hint == name for hint in hints):
                columns[key] = index
                break

    # Tahap 2: substring match untuk kolom yang belum ketemu
    for key, hints in COLUMN_HINTS:
        if key in columns:
            continue
        for index, name in enumerate(normalized):
            if not name or blocked(key, name):
                continue
            if any(hint in name for hint in hints):
                columns[key] = index
                break

    return columns


def _parse_date(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return to_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def _parse_time(value: str) -> tuple[int, int, int] | None:
    """Baca jam dari kolom terpisah ("14:30" / "14:30:15")."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in TIME_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.hour, parsed.minute, parsed.second
    return None


def _combine_date_time(date_value: str, time_value: str) -> datetime | None:
    """Gabungkan kolom Tanggal + Waktu jadi satu datetime UTC.

    Kalau kolom Tanggal sudah memuat jam, jam dari kolom Waktu diabaikan.
    Kalau kolom Tanggal hanya tanggal, jam dari kolom Waktu dipakai supaya
    jam transaksi tidak hilang saat export -> import.
    """
    text = (date_value or "").strip()
    if not text:
        return None

    has_time = any(
        marker in text for marker in (":", "T")
    ) and not text.count("-") == 0
    parsed = _parse_date(text)

    if parsed is None:
        return None

    if has_time:
        return parsed

    clock = _parse_time(time_value)
    if clock is None:
        return parsed

    # parsed sudah UTC; konversi balik ke waktu lokal untuk menempelkan jam
    # dari file (jam di file adalah waktu lokal pengguna).
    local = parsed.replace(tzinfo=timezone.utc).astimezone(TZ)
    local = local.replace(hour=clock[0], minute=clock[1], second=clock[2], microsecond=0)
    return to_utc(local)


def _parse_kind(value: str, default: str = "expense") -> str:
    text = (value or "").strip().lower()
    if not text:
        return default
    for word in TRANSFER_WORDS:
        if word in text:
            return "transfer"
    for word in INCOME_WORDS:
        if word in text:
            return "income"
    for word in EXPENSE_WORDS:
        if word in text:
            return "expense"
    return default


def _parse_account_kind(value: str) -> str | None:
    """Terjemahkan jenis dompet dari file ke cash | bank | ewallet.

    Mengembalikan None kalau kolom kosong / tidak dikenali, supaya
    ``wallet.guess_kind()`` yang menebak dari nama dompet.
    """
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in ACCOUNT_KIND_ALIASES:
        return ACCOUNT_KIND_ALIASES[text]
    for alias, kind in ACCOUNT_KIND_ALIASES.items():
        if alias in text:
            return kind
    return None


def _get_or_create_category(db: Session, name: str, kind: str) -> tuple[Category | None, bool]:
    clean = " ".join((name or "").split())
    if not clean:
        return None, False

    existing = db.scalar(select(Category).where(func.lower(Category.name) == clean.lower()).limit(1))
    if existing is not None:
        return existing, False

    category = Category(name=clean[:60], kind=kind)
    db.add(category)
    db.flush()
    return category, True


def import_csv(db: Session, content: bytes | str, source: str = "import") -> ImportResult:
    """Import transaksi dari CSV dan sinkronkan saldo dompet."""
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = content

    result = ImportResult()

    # Lewati baris komentar & baris kosong (dipakai backup CSV untuk
    # menyertakan snapshot dompet tanpa mengganggu proses import).
    cleaned_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not cleaned_lines:
        result.messages.append("File CSV kosong atau tidak punya baris data.")
        result.errors = 1
        return result

    rows = list(csv.reader(StringIO("\n".join(cleaned_lines))))
    if len(rows) < 2:
        result.messages.append("File CSV kosong atau tidak punya baris data.")
        result.errors = 1
        return result

    header = rows[0]
    columns = _detect_columns(header)

    if "amount" not in columns:
        result.messages.append("Kolom nominal tidak ditemukan.")
        result.errors = 1
        return result

    # Dompet fallback kalau file tidak menyebut nama dompet.
    default_account = wallet.ensure_default_account(db)
    account_cache: dict[str, Account] = {
        account.name.lower(): account for account in db.scalars(select(Account)).all()
    }

    def resolve_account(raw: str, kind_hint: str | None = None) -> Account:
        """Cari/buat dompet dari nama; jenis dompet ikut dari file kalau ada."""
        name = wallet.normalize_name(raw)
        if not name:
            return default_account

        key = name.lower()
        if key in account_cache:
            account = account_cache[key]
            # File boleh mengoreksi jenis dompet yang sudah ada.
            if kind_hint and account.kind != kind_hint:
                account.kind = kind_hint
            return account

        account, created = wallet.get_or_create_account(db, name, kind=kind_hint)
        account_cache[key] = account
        if created:
            result.accounts_created.append(account.name)
        return account

    def cell(row: list[str], key: str) -> str:
        index = columns.get(key)
        if index is None or index >= len(row):
            return ""
        return row[index].strip()

    for row_index, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue

        try:
            amount = parse_amount(cell(row, "amount")) if "amount" in columns else None
            if not amount or amount <= 0:
                result.errors += 1
                result.messages.append(f"Baris {row_index}: nominal tidak valid.")
                continue

            kind = _parse_kind(cell(row, "kind"), default="expense")
            if not cell(row, "kind") and cell(row, "category"):
                # Beberapa file menandai pemasukan lewat nama kategori.
                lowered = cell(row, "category").lower()
                if any(word in lowered for word in ("gaji", "bonus", "thr", "pemasukan", "refund")):
                    kind = "income"

            occurred_at = _combine_date_time(cell(row, "date"), cell(row, "time"))
            if occurred_at is None:
                occurred_at = to_utc(datetime.now())

            category = None
            if kind != "transfer" and cell(row, "category"):
                category, created = _get_or_create_category(
                    db, cell(row, "category"), "income" if kind == "income" else "expense"
                )
                if created and category is not None:
                    result.categories_created.append(category.name)

            # Jenis dompet dari file (tunai/bank/e-wallet). Kalau kosong,
            # wallet.guess_kind() menebak dari nama dompet.
            kind_hint = _parse_account_kind(cell(row, "account_kind"))

            account = default_account
            if cell(row, "account"):
                account = resolve_account(cell(row, "account"), kind_hint)

            # Dompet tujuan untuk transfer (kolom "Dompet Tujuan" / "Ke Dompet").
            # Jenis dompet tujuan TIDAK diambil dari kolom "Jenis Dompet", karena
            # kolom itu milik dompet asal; jenisnya ditebak dari nama.
            to_account = None
            if kind == "transfer" and cell(row, "to_account"):
                to_account = resolve_account(cell(row, "to_account"))

            if kind == "transfer":
                if to_account is None or to_account.id == account.id:
                    result.errors += 1
                    result.messages.append(
                        f"Baris {row_index}: transfer butuh dompet tujuan yang berbeda."
                    )
                    continue
            else:
                to_account = None

            merchant = cell(row, "merchant")[:120] or None

            db.add(
                Transaction(
                    kind=kind,
                    amount=amount,
                    account_id=account.id,
                    to_account_id=to_account.id if to_account else None,
                    category_id=category.id if category and kind != "transfer" else None,
                    merchant=merchant,
                    occurred_at=occurred_at,
                    source=source,
                    status="confirmed",
                    category_source="import",
                )
            )
            result.imported += 1
        except Exception as exc:  # noqa: BLE001 - satu baris gagal tidak boleh membatalkan semua
            result.errors += 1
            result.messages.append(f"Baris {row_index}: {exc}")

    db.commit()

    # Setelah transaksi masuk, hitung ulang saldo semua dompet supaya
    # dompet baru langsung terisi sesuai nilai transaksinya.
    snapshot = wallet.sync_balances(db)
    result.wallets = [
        {"id": item["id"], "name": item["name"], "balance": item["balance"]}
        for item in snapshot
        if not item["archived"]
    ]

    if result.imported == 0 and result.errors:
        result.messages.append("Tidak ada transaksi yang berhasil diimport.")

    return result


def is_csv_filename(name: str) -> bool:
    return bool(re.search(r"\.csv$", (name or "").strip(), re.IGNORECASE))
