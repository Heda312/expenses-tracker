"""Saldo dompet yang selalu mengikuti transaksi.

Sumber kebenaran saldo adalah tabel ``transactions``. Tidak ada saldo yang
"dipatok" saat dompet dibuat: saldo dihitung ulang dari pemasukan,
pengeluaran, dan transfer setiap kali dibutuhkan.

Kolom ``accounts.cached_balance`` hanya cache supaya pembacaan cepat
(API/bot) tidak perlu agregasi terus-menerus. Cache selalu diperbarui lewat
:func:`sync_balances`, jadi nilainya tidak pernah menyimpang dari transaksi.
"""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Account, Transaction, utcnow

ACTIVE = (Transaction.status == "confirmed", Transaction.deleted_at.is_(None))

# Nama dompet yang sering muncul di mutasi bank / struk -> jenis dompet.
BANK_HINTS = (
    "bca", "mandiri", "bri", "bni", "btn", "cimb", "permata", "danamon",
    "jago", "seabank", "blu", "jenius", "ocbc", "panin", "mega", "bank",
)
EWALLET_HINTS = (
    "gopay", "go pay", "ovo", "dana", "shopeepay", "shopee pay", "linkaja",
    "link aja", "qris", "sakuku", "i.saku", "ewallet", "e-wallet", "dompet digital",
)

DEFAULT_ACCOUNT_NAME = "Cash"


def guess_kind(name: str) -> str:
    """Tebak jenis dompet dari namanya (cash | bank | ewallet)."""
    lowered = (name or "").strip().lower()
    if any(hint in lowered for hint in EWALLET_HINTS):
        return "ewallet"
    if any(hint in lowered for hint in BANK_HINTS):
        return "bank"
    return "cash"


def normalize_name(name: str) -> str:
    return " ".join((name or "").split())


def _flows(db: Session):
    """Subquery agregat arus kas per dompet dalam satu query."""
    outgoing = (
        select(
            Transaction.account_id.label("account_id"),
            func.coalesce(
                func.sum(case((Transaction.kind == "income", Transaction.amount), else_=0)), 0
            ).label("income"),
            func.coalesce(
                func.sum(case((Transaction.kind == "expense", Transaction.amount), else_=0)), 0
            ).label("expense"),
            func.coalesce(
                func.sum(case((Transaction.kind == "transfer", Transaction.amount), else_=0)), 0
            ).label("transfer_out"),
            func.count(Transaction.id).label("out_count"),
        )
        .where(*ACTIVE)
        .group_by(Transaction.account_id)
        .subquery()
    )

    incoming = (
        select(
            Transaction.to_account_id.label("account_id"),
            func.coalesce(func.sum(Transaction.amount), 0).label("transfer_in"),
            func.count(Transaction.id).label("in_count"),
        )
        .where(Transaction.kind == "transfer", *ACTIVE)
        .group_by(Transaction.to_account_id)
        .subquery()
    )

    return outgoing, incoming


def balances(db: Session, include_archived: bool = False) -> list[dict]:
    """Hitung saldo semua dompet dari transaksi.

    Return list of dict: id, name, kind, archived, opening_balance,
    income, expense, transfer_out, transfer_in, transaction_count, balance.
    """
    outgoing, incoming = _flows(db)

    query = (
        select(
            Account.id,
            Account.name,
            Account.kind,
            Account.archived,
            Account.opening_balance,
            Account.cached_balance,
            Account.balance_updated_at,
            func.coalesce(outgoing.c.income, 0).label("income"),
            func.coalesce(outgoing.c.expense, 0).label("expense"),
            func.coalesce(outgoing.c.transfer_out, 0).label("transfer_out"),
            func.coalesce(outgoing.c.out_count, 0).label("out_count"),
            func.coalesce(incoming.c.transfer_in, 0).label("transfer_in"),
            func.coalesce(incoming.c.in_count, 0).label("in_count"),
        )
        .outerjoin(outgoing, Account.id == outgoing.c.account_id)
        .outerjoin(incoming, Account.id == incoming.c.account_id)
        .order_by(Account.archived, Account.name)
    )
    if not include_archived:
        query = query.where(Account.archived.is_(False))

    result = []
    for row in db.execute(query):
        balance = (
            int(row.opening_balance or 0)
            + int(row.income or 0)
            - int(row.expense or 0)
            - int(row.transfer_out or 0)
            + int(row.transfer_in or 0)
        )
        result.append(
            {
                "id": row.id,
                "name": row.name,
                "kind": row.kind,
                "archived": bool(row.archived),
                "opening_balance": int(row.opening_balance or 0),
                "income": int(row.income or 0),
                "expense": int(row.expense or 0),
                "transfer_out": int(row.transfer_out or 0),
                "transfer_in": int(row.transfer_in or 0),
                "transaction_count": int(row.out_count or 0) + int(row.in_count or 0),
                "balance": balance,
                "cached_balance": int(row.cached_balance or 0),
                "balance_updated_at": row.balance_updated_at,
                "in_sync": int(row.cached_balance or 0) == balance,
            }
        )

    return result


def balances_map(db: Session, include_archived: bool = True) -> dict[int, int]:
    return {
        item["id"]: item["balance"]
        for item in balances(db, include_archived=include_archived)
    }


def total_balance(db: Session) -> int:
    return sum(item["balance"] for item in balances(db))


def sync_balances(db: Session, commit: bool = True) -> list[dict]:
    """Perbarui ``accounts.cached_balance`` dari transaksi.

    Dipanggil setelah transaksi berubah (web, bot, import) dan saat startup.
    Mengembalikan daftar saldo terbaru (semua dompet, termasuk arsip).
    """
    snapshot = balances(db, include_archived=True)
    stamp = utcnow()

    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    for item in snapshot:
        account = accounts.get(item["id"])
        if account is None:
            continue
        account.cached_balance = item["balance"]
        account.balance_updated_at = stamp
        item["cached_balance"] = item["balance"]
        item["balance_updated_at"] = stamp
        item["in_sync"] = True

    # Selalu commit: pemanggil mungkin punya perubahan lain yang belum
    # disimpan (misalnya dompet baru hasil auto-create saat import).
    if commit:
        db.commit()

    return snapshot


def get_or_create_account(
    db: Session,
    name: str,
    kind: str | None = None,
    opening_balance: int = 0,
    flush: bool = True,
) -> tuple[Account, bool]:
    """Cari dompet berdasarkan nama (case-insensitive), buat kalau belum ada.

    Dipakai saat import supaya kolom "Dompet" di file langsung terhubung ke
    transaksi tanpa perlu membuat dompet manual lebih dulu.
    """
    clean = normalize_name(name)
    if not clean:
        clean = DEFAULT_ACCOUNT_NAME

    existing = db.scalar(
        select(Account).where(func.lower(Account.name) == clean.lower()).limit(1)
    )
    if existing is not None:
        return existing, False

    account = Account(
        name=clean,
        kind=kind or guess_kind(clean),
        opening_balance=int(opening_balance or 0),
        cached_balance=0,
    )
    db.add(account)
    if flush:
        db.flush()
    return account, True


def ensure_default_account(db: Session) -> Account:
    """Dompet fallback kalau file import tidak menyebut nama dompet."""
    account = db.scalar(select(Account).where(Account.archived.is_(False)).order_by(Account.id).limit(1))
    if account is not None:
        return account
    account, _ = get_or_create_account(db, DEFAULT_ACCOUNT_NAME, kind="cash")
    return account


def resolve_account(db: Session, value: int | str | None) -> Account | None:
    """Cari dompet dari id atau nama."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        return db.get(Account, int(value))
    return db.scalar(
        select(Account).where(func.lower(Account.name) == normalize_name(str(value)).lower()).limit(1)
    )
