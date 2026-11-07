"""Tes hapus akun, export CSV round-trip, dan loading state.

Tiga bug yang dijaga di sini:
1. Form hapus akun tidak mengirim ``confirm_password`` sehingga backend selalu
   menolak, dan kategori/budget tidak ikut terhapus.
2. Class ``loading`` dipakai untuk tombol/form padahal di CSS class itu adalah
   spinner, sehingga teks tombol ikut berputar.
3. CSV export tidak bisa di-import ulang dengan kondisi dompet yang sama
   (transfer kehilangan dompet tujuan, saldo awal dompet hilang).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete as sa_delete  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    Budget,
    Category,
    Transaction,
    User,
    utcnow,
)
from app.services import importer, wallet  # noqa: E402

PASSWORD = "passwordpanjang123"
APP_DIR = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture()
def client():
    """Client yang sudah login; DB dibersihkan otomatis oleh conftest."""
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


def _seed_data() -> None:
    with SessionLocal() as db:
        account = Account(name="BCA", kind="bank", opening_balance=1_000_000)
        target = Account(name="GoPay", kind="ewallet")
        expense_cat = Category(name="Makanan", kind="expense", color="#f00")
        income_cat = Category(name="Gaji", kind="income", color="#0f0")
        db.add_all([account, target, expense_cat, income_cat])
        db.flush()
        db.add(Budget(category_id=expense_cat.id, period="2026-11", amount=1_000_000))
        db.add_all(
            [
                Transaction(
                    kind="expense",
                    amount=150_000,
                    account_id=account.id,
                    category_id=expense_cat.id,
                    merchant="Indomaret",
                    occurred_at=utcnow(),
                    status="confirmed",
                ),
                Transaction(
                    kind="income",
                    amount=3_000_000,
                    account_id=account.id,
                    category_id=income_cat.id,
                    merchant="Kantor",
                    occurred_at=utcnow(),
                    status="confirmed",
                ),
                Transaction(
                    kind="transfer",
                    amount=500_000,
                    account_id=account.id,
                    to_account_id=target.id,
                    occurred_at=utcnow(),
                    status="confirmed",
                ),
            ]
        )
        db.commit()


# ---------------------------------------------------------------------------
# 1. Hapus akun
# ---------------------------------------------------------------------------


def test_delete_account_removes_all_data_and_redirects_to_register(client):
    _seed_data()

    response = client.post(
        "/settings/delete-account",
        data={"password": PASSWORD, "confirm_password": PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/register?flash=deleted"
    assert "sid=" in response.headers.get("set-cookie", "")

    with SessionLocal() as db:
        assert db.scalar(select(User.id).limit(1)) is None
        assert db.scalar(select(Account.id).limit(1)) is None
        assert db.scalar(select(Category.id).limit(1)) is None
        assert db.scalar(select(Transaction.id).limit(1)) is None
        assert db.scalar(select(Budget.id).limit(1)) is None


def test_delete_account_shows_confirmation_on_register_page():
    # Client tanpa sesi: halaman register hanya tampil untuk pengunjung anonim.
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/register?flash=deleted")

    assert response.status_code == 200
    assert "Akun berhasil dihapus" in response.text


def test_delete_account_rejects_wrong_password(client):
    _seed_data()

    response = client.post(
        "/settings/delete-account",
        data={"password": "salahbanget123", "confirm_password": "salahbanget123"},
        follow_redirects=False,
    )

    assert "flash=wrong_password" in response.headers["location"]
    with SessionLocal() as db:
        assert db.scalar(select(User.id).limit(1)) is not None


def test_delete_account_form_has_confirm_password_field():
    html = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")

    assert 'name="confirm_password"' in html
    assert 'name="password"' in html


# ---------------------------------------------------------------------------
# 2. Export CSV round-trip
# ---------------------------------------------------------------------------


def test_export_csv_round_trip_preserves_wallets_and_transactions(client):
    _seed_data()

    with SessionLocal() as db:
        before = {item["name"]: item["balance"] for item in wallet.balances(db)}
        before_count = sum(item["transaction_count"] for item in wallet.balances(db))

    response = client.get("/export/transaksi.csv")
    assert response.status_code == 200, response.text[:200]
    csv_text = response.content.decode("utf-8-sig")

    header = csv_text.splitlines()[0]
    # Export hanya transaksi; jenis dompet & jam ikut dibawa.
    for column in ("Tanggal", "Waktu", "Jenis", "Nominal", "Dompet", "Jenis Dompet", "Dompet Tujuan"):
        assert column in header, column
    assert "Saldo Awal" not in header

    # Kosongkan data lalu import ulang file yang sama.
    with SessionLocal() as db:
        db.execute(sa_delete(Transaction))
        db.execute(sa_delete(Budget))
        db.execute(sa_delete(Account))
        db.execute(sa_delete(Category))
        db.commit()

    with SessionLocal() as db:
        result = importer.import_csv(db, csv_text.encode("utf-8"), source="reimport")

    assert result.imported == 3
    assert result.errors == 0

    with SessionLocal() as db:
        after = {item["name"]: item["balance"] for item in wallet.balances(db)}
        after_count = sum(item["transaction_count"] for item in wallet.balances(db))
        after_kinds = {acc.name: acc.kind for acc in db.scalars(select(Account)).all()}

    assert after_count == before_count
    # Jenis dompet harus terbawa lewat kolom "Jenis Dompet".
    assert after_kinds["BCA"] == "bank"
    assert after_kinds["GoPay"] == "ewallet"
    # Saldo dompet murni dari transaksi (saldo awal tidak diekspor).
    assert after["BCA"] == before["BCA"] - 1_000_000
    assert after["GoPay"] == before["GoPay"]


def test_import_keeps_transfer_target_wallet():
    csv_text = (
        "Tanggal,Jenis,Nominal,Dompet,Dompet Tujuan\n"
        "2026-11-07,Transfer,250000,BCA,GoPay\n"
    )

    with SessionLocal() as db:
        result = importer.import_csv(db, csv_text, source="test")
    assert result.imported == 1

    with SessionLocal() as db:
        transfer = db.scalar(select(Transaction))
        assert transfer.kind == "transfer"
        assert transfer.to_account is not None
        assert transfer.to_account.name == "GoPay"


def test_import_uses_account_kind_column():
    csv_text = (
        "Tanggal,Jenis,Nominal,Kategori,Dompet,Jenis Dompet\n"
        "2026-11-07,Pengeluaran,10000,Makanan,BCA,Bank\n"
        "2026-11-07,Pengeluaran,20000,Makanan,GoPay,E-wallet\n"
        "2026-11-07,Pengeluaran,30000,Makanan,Uang Saku,Tunai\n"
    )

    with SessionLocal() as db:
        result = importer.import_csv(db, csv_text, source="test")
    assert result.imported == 3

    with SessionLocal() as db:
        kinds = {acc.name: acc.kind for acc in db.scalars(select(Account)).all()}

    assert kinds["BCA"] == "bank"
    assert kinds["GoPay"] == "ewallet"
    assert kinds["Uang Saku"] == "cash"


def test_import_guesses_kind_when_column_missing():
    csv_text = (
        "Tanggal,Jenis,Nominal,Kategori,Dompet\n"
        "2026-11-07,Pengeluaran,10000,Makanan,BCA\n"
        "2026-11-07,Pengeluaran,20000,Makanan,GoPay\n"
        "2026-11-07,Pengeluaran,30000,Makanan,Dompet Harian\n"
    )

    with SessionLocal() as db:
        importer.import_csv(db, csv_text, source="test")

    with SessionLocal() as db:
        kinds = {acc.name: acc.kind for acc in db.scalars(select(Account)).all()}

    # Tanpa kolom jenis, jenis ditebak dari nama dompet.
    assert kinds["BCA"] == "bank"
    assert kinds["GoPay"] == "ewallet"
    assert kinds["Dompet Harian"] == "cash"


def test_wallet_export_endpoints_removed(client):
    """Export dompet, backup, dan format bank sudah dihapus."""
    assert client.get("/export/dompet.csv").status_code == 404
    assert client.get("/export/backup.csv").status_code == 404
    assert client.get("/export/umum.csv").status_code == 404
    assert client.get("/export/bca.csv").status_code == 404


def test_export_time_round_trip(client):
    """Jam transaksi tidak boleh hilang saat export -> import."""
    from datetime import datetime

    from app.services.dates import to_local, to_utc

    with SessionLocal() as db:
        account = Account(name="BCA", kind="bank")
        db.add(account)
        db.flush()
        for stamp in ("2026-11-07 09:15:00", "2026-11-07 13:42:30", "2026-11-07 23:59:00"):
            db.add(
                Transaction(
                    kind="expense",
                    amount=10_000,
                    account_id=account.id,
                    occurred_at=to_utc(datetime.fromisoformat(stamp)),
                    status="confirmed",
                )
            )
        db.commit()

    with SessionLocal() as db:
        before = sorted(
            to_local(t.occurred_at).strftime("%Y-%m-%d %H:%M:%S")
            for t in db.scalars(select(Transaction)).all()
        )

    response = client.get("/export/transaksi.csv")
    assert response.status_code == 200
    csv_text = response.content.decode("utf-8-sig")

    with SessionLocal() as db:
        db.execute(sa_delete(Transaction))
        db.execute(sa_delete(Account))
        db.commit()

    with SessionLocal() as db:
        result = importer.import_csv(db, csv_text.encode("utf-8"), source="reimport")
    assert result.imported == 3

    with SessionLocal() as db:
        after = sorted(
            to_local(t.occurred_at).strftime("%Y-%m-%d %H:%M:%S")
            for t in db.scalars(select(Transaction)).all()
        )

    assert after == before, f"jam berubah: {before} -> {after}"


def test_import_time_column_combines_with_date():
    """Kolom Waktu digabung dengan Tanggal (jam lokal)."""
    csv_text = (
        "Tanggal,Waktu,Jenis,Nominal,Dompet\n"
        "2026-11-07,14:30:00,Pengeluaran,10000,BCA\n"
        "2026-11-07,,Pengeluaran,20000,BCA\n"
    )

    with SessionLocal() as db:
        result = importer.import_csv(db, csv_text, source="test")
    assert result.imported == 2

    with SessionLocal() as db:
        from app.services.dates import to_local

        rows = sorted(
            to_local(t.occurred_at).strftime("%Y-%m-%d %H:%M:%S")
            for t in db.scalars(select(Transaction)).all()
        )

    assert "2026-11-07 14:30:00" in rows
    # Tanpa kolom waktu, jam jadi 00:00 (bukan jam sekarang).
    assert "2026-11-07 00:00:00" in rows


# ---------------------------------------------------------------------------
# 3. Loading state tidak memutar teks
# ---------------------------------------------------------------------------


def test_loading_class_is_spinner_only_and_submit_uses_separate_class():
    css = (APP_DIR / "static" / "app.css").read_text(encoding="utf-8")

    # ".loading" tetap spinner mandiri
    assert ".loading {" in css
    # state tombol/form memakai class terpisah
    assert ".btn.is-submitting" in css
    assert "form.is-submitting" in css
    # jangan pasang spinner ke tombol
    assert ".btn.loading::after" not in css
    assert "form.loading {" not in css


def test_loading_js_does_not_use_spinner_class():
    js = (APP_DIR / "static" / "loading.js").read_text(encoding="utf-8")

    assert "is-submitting" in js
    # Pastikan tidak ada pemanggilan classList yang memakai "loading".
    assert 'classList.add("loading")' not in js
    assert "classList.add('loading')" not in js
    assert 'classList.remove("loading")' not in js
    assert "classList.remove('loading')" not in js


def test_upload_overlay_has_single_display_value():
    html = (APP_DIR / "templates" / "transactions.html").read_text(encoding="utf-8")

    overlay_lines = [line for line in html.splitlines() if 'id="upload-loading"' in line]
    assert overlay_lines, "overlay OCR harus ada"
    # Dua nilai display membuat overlay selalu terlihat.
    assert overlay_lines[0].count("display:") == 1
