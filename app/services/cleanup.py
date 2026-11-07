"""Penghapusan dompet & kategori yang aman terhadap foreign key.

Masalah yang diselesaikan:

- Transaksi memakai *soft delete* (``deleted_at`` diisi), jadi barisnya masih
  ada di database dan masih mereferensikan ``accounts.id`` / ``categories.id``.
  Akibatnya dompet/kategori tidak bisa dihapus walau transaksinya sudah
  "dihapus" dari sudut pandang pengguna, dan ``db.delete()`` gagal dengan
  ``FOREIGN KEY constraint failed``.

Aturan yang dipakai:

- Yang dianggap "masih punya transaksi" hanya transaksi **aktif**
  (``deleted_at IS NULL``). Selama ada transaksi aktif, dompet/kategori tidak
  boleh dihapus supaya laporan tidak berubah diam-diam.
- Kalau semua transaksinya sudah di-soft-delete, penghapusan dilanjutkan:
  baris transaksi yang sudah mati itu dibersihkan (purge) untuk dompet, atau
  dilepas referensinya (set NULL) untuk kategori.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Account, Budget, Category, Merchant, Transaction


@dataclass
class DeleteResult:
    deleted: bool
    reason: str = ""
    active_transactions: int = 0
    purged_transactions: int = 0
    detached_transactions: int = 0
    deleted_budgets: int = 0
    deleted_merchants: int = 0


def count_active_account_transactions(db: Session, account_id: int) -> int:
    """Jumlah transaksi aktif yang memakai dompet ini (sebagai asal atau tujuan)."""
    return int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.deleted_at.is_(None),
                or_(
                    Transaction.account_id == account_id,
                    Transaction.to_account_id == account_id,
                ),
            )
        )
        or 0
    )


def count_active_category_transactions(db: Session, category_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.deleted_at.is_(None),
                Transaction.category_id == category_id,
            )
        )
        or 0
    )


def delete_account(db: Session, account_id: int, force: bool = False) -> DeleteResult:
    """Hapus dompet beserta sisa data yang masih mereferensikannya.

    ``force=True`` menghapus juga transaksi yang masih aktif. Tanpa force,
    dompet yang masih punya transaksi aktif tidak akan dihapus.
    """
    account = db.get(Account, account_id)
    if account is None:
        return DeleteResult(deleted=False, reason="notfound")

    active = count_active_account_transactions(db, account_id)
    if active and not force:
        return DeleteResult(
            deleted=False,
            reason="has_transactions",
            active_transactions=active,
        )

    # Semua baris transaksi milik dompet ini harus hilang/dilepas dulu,
    # karena accounts.id masih direferensikan (FK NO ACTION).
    rows = db.execute(
        select(Transaction.id, Transaction.account_id, Transaction.to_account_id).where(
            or_(
                Transaction.account_id == account_id,
                Transaction.to_account_id == account_id,
            )
        )
    ).all()

    purged = 0
    detached = 0
    to_purge: list[int] = []
    to_detach: list[int] = []
    for tx_id, source_account_id, target_account_id in rows:
        if source_account_id == account_id:
            # account_id NOT NULL -> satu-satunya jalan adalah hapus barisnya.
            to_purge.append(tx_id)
        elif target_account_id == account_id:
            # to_account_id nullable -> cukup dilepas supaya riwayat tetap ada.
            to_detach.append(tx_id)

    if to_purge:
        db.execute(delete(Transaction).where(Transaction.id.in_(to_purge)))
        purged = len(to_purge)
    if to_detach:
        db.execute(
            update(Transaction)
            .where(Transaction.id.in_(to_detach))
            .values(to_account_id=None)
        )
        detached = len(to_detach)

    db.delete(account)
    db.commit()

    return DeleteResult(
        deleted=True,
        purged_transactions=purged,
        detached_transactions=detached,
        active_transactions=active,
    )


def delete_category(db: Session, category_id: int) -> DeleteResult:
    """Hapus kategori; transaksi aktif tetap dilindungi.

    Kalau kategori hanya dipakai transaksi yang sudah di-soft-delete, referensi
    dilepas (``category_id = NULL``) supaya riwayat transaksi tetap utuh.
    """
    category = db.get(Category, category_id)
    if category is None:
        return DeleteResult(deleted=False, reason="notfound")

    active = count_active_category_transactions(db, category_id)
    if active:
        return DeleteResult(
            deleted=False,
            reason="has_transactions",
            active_transactions=active,
        )

    # Transaksi yang sudah dihapus: lepas referensinya, jangan hapus barisnya.
    detached = db.execute(
        update(Transaction)
        .where(Transaction.category_id == category_id)
        .values(category_id=None)
    ).rowcount or 0

    deleted_budgets = db.execute(
        delete(Budget).where(Budget.category_id == category_id)
    ).rowcount or 0

    deleted_merchants = db.execute(
        update(Merchant).where(Merchant.category_id == category_id).values(category_id=None)
    ).rowcount or 0

    db.delete(category)
    db.commit()

    return DeleteResult(
        deleted=True,
        detached_transactions=int(detached),
        deleted_budgets=int(deleted_budgets),
        deleted_merchants=int(deleted_merchants),
    )
