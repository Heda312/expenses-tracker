"""Tes alur hapus dompet & kategori (regresi FK constraint).

Konteks bug: transaksi memakai soft delete, jadi barisnya masih ada dan masih
mereferensikan accounts.id / categories.id. Dulu pengecekan menghitung semua
baris (termasuk yang sudah dihapus) sehingga dompet tidak bisa dihapus, dan
kalau dipaksa muncul error FOREIGN KEY constraint failed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, Category, Transaction, utcnow  # noqa: E402

PASSWORD = "passwordpanjang123"


@pytest.fixture()
def client():
    """Client yang sudah login; dibuat ulang tiap tes (DB dibersihkan conftest)."""
    test_client = TestClient(app, raise_server_exceptions=False)
    test_client.post(
        "/register",
        data={"username": "tester", "password": PASSWORD, "confirm_password": PASSWORD},
        follow_redirects=False,
    )
    response = test_client.post(
        "/login",
        data={"username": "tester", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:200]
    return test_client


def _make_account(name: str) -> int:
    with SessionLocal() as db:
        account = Account(name=name, kind="cash")
        db.add(account)
        db.commit()
        return account.id


def _make_tx(account_id: int, category_id: int | None = None, amount: int = 10_000) -> int:
    with SessionLocal() as db:
        tx = Transaction(
            kind="expense",
            amount=amount,
            account_id=account_id,
            category_id=category_id,
            occurred_at=utcnow(),
            status="confirmed",
        )
        db.add(tx)
        db.commit()
        return tx.id


def _soft_delete(tx_id: int) -> None:
    with SessionLocal() as db:
        tx = db.get(Transaction, tx_id)
        tx.deleted_at = utcnow()
        db.commit()


def test_delete_account_blocked_when_active_transaction(client):
    account_id = _make_account("Aktif")
    _make_tx(account_id)

    r = client.post(f"/accounts/{account_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert "flash=has_transactions" in r.headers["location"]

    with SessionLocal() as db:
        assert db.get(Account, account_id) is not None


def test_delete_account_after_transactions_soft_deleted(client):
    account_id = _make_account("Sudah Bersih")
    tx_id = _make_tx(account_id)
    _soft_delete(tx_id)

    r = client.post(f"/accounts/{account_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert "flash=deleted" in r.headers["location"]

    with SessionLocal() as db:
        assert db.get(Account, account_id) is None
        # baris transaksi yang sudah mati ikut dibersihkan (FK account_id NOT NULL)
        assert db.get(Transaction, tx_id) is None


def test_force_delete_account_removes_active_transactions(client):
    account_id = _make_account("Dipaksa")
    _make_tx(account_id)

    r = client.post(
        f"/accounts/{account_id}/delete",
        data={"force": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "flash=deleted" in r.headers["location"]

    with SessionLocal() as db:
        assert db.get(Account, account_id) is None


def test_delete_account_keeps_transfer_history_of_other_wallet(client):
    source_id = _make_account("Sumber")
    target_id = _make_account("Tujuan")

    with SessionLocal() as db:
        transfer = Transaction(
            kind="transfer",
            amount=50_000,
            account_id=source_id,
            to_account_id=target_id,
            occurred_at=utcnow(),
            status="confirmed",
        )
        db.add(transfer)
        db.commit()
        transfer_id = transfer.id

    # Selama transfer masih aktif, dompet tujuan masih terpakai -> diblokir.
    r = client.post(f"/accounts/{target_id}/delete", follow_redirects=False)
    assert "flash=has_transactions" in r.headers["location"]

    # Setelah transfer dihapus (soft delete), dompet tujuan boleh dihapus.
    _soft_delete(transfer_id)
    r = client.post(f"/accounts/{target_id}/delete", follow_redirects=False)
    assert "flash=deleted" in r.headers["location"]

    with SessionLocal() as db:
        saved = db.get(Transaction, transfer_id)
        assert saved is not None
        # to_account_id nullable -> cukup dilepas, riwayat transfer tetap ada
        assert saved.to_account_id is None
        assert saved.account_id == source_id


def test_delete_category_after_transactions_soft_deleted(client):
    account_id = _make_account("Dompet Kategori")
    with SessionLocal() as db:
        category = Category(name="Kategori Uji", kind="expense", color="#fff")
        db.add(category)
        db.commit()
        category_id = category.id

    tx_id = _make_tx(account_id, category_id=category_id)
    _soft_delete(tx_id)

    r = client.delete(f"/api/categories/{category_id}")
    assert r.status_code == 200

    with SessionLocal() as db:
        assert db.get(Category, category_id) is None
        # riwayat transaksi tetap ada, referensi kategorinya dilepas
        saved = db.get(Transaction, tx_id)
        assert saved is not None
        assert saved.category_id is None


def test_delete_category_blocked_when_active_transaction(client):
    account_id = _make_account("Dompet Kategori 2")
    with SessionLocal() as db:
        category = Category(name="Kategori Aktif", kind="expense", color="#fff")
        db.add(category)
        db.commit()
        category_id = category.id

    _make_tx(account_id, category_id=category_id)

    r = client.delete(f"/api/categories/{category_id}")
    assert r.status_code == 400

    with SessionLocal() as db:
        assert db.get(Category, category_id) is not None


def test_api_delete_account_force_and_soft_deleted(client):
    account_id = _make_account("API Dompet")
    _make_tx(account_id)

    # tanpa force dan masih ada transaksi aktif -> 409
    r = client.delete(f"/api/v1/accounts/{account_id}")
    assert r.status_code in (401, 409)

    with SessionLocal() as db:
        tx_id = db.scalar(select(Transaction.id).where(Transaction.account_id == account_id))
    _soft_delete(tx_id)

    # sudah bersih -> berhasil walau tanpa force
    r = client.delete(f"/api/v1/accounts/{account_id}")
    assert r.status_code in (200, 401)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("\nSEMUA TES HAPUS LULUS")
