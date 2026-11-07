"""Smoke test halaman web dompet & import CSV pada database sementara."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEMP = Path(tempfile.gettempdir()) / "opencode" / "_wallet_web_test.db"
TEMP.parent.mkdir(parents=True, exist_ok=True)
if TEMP.exists():
    TEMP.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP.as_posix()}"
os.environ["AUTO_MIGRATE"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import wallet  # noqa: E402

Base.metadata.create_all(engine)

client = TestClient(app, raise_server_exceptions=True)

r = client.post(
    "/register",
    data={"username": "tester", "password": "passwordpanjang123", "confirm_password": "passwordpanjang123"},
    follow_redirects=False,
)
print("register:", r.status_code, r.headers.get("location"))

r = client.post(
    "/login",
    data={"username": "tester", "password": "passwordpanjang123"},
    follow_redirects=False,
)
print("login:", r.status_code, r.headers.get("location"))
assert r.status_code == 303

# Buat dompet lewat form web
r = client.post(
    "/accounts/create",
    data={"name": "Dompet Uji", "kind": "cash", "opening_balance": "200000"},
    follow_redirects=False,
)
print("create account:", r.status_code)
assert r.status_code == 303

# Halaman dompet tampil
r = client.get("/accounts")
print("accounts page:", r.status_code)
assert r.status_code == 200
assert "Dompet Uji" in r.text
assert "Rp 200.000" in r.text

# Import CSV lewat endpoint web: dompet baru otomatis dibuat
csv_text = (
    "Tanggal,Nominal,Kategori,Merchant,Dompet\n"
    "2026-02-01,100000,Makanan,Bakso,Wallet Import\n"
    "2026-02-02,50000,Transport,Ojek,Wallet Import\n"
)
r = client.post(
    "/api/import-csv",
    files={"file": ("data.csv", csv_text.encode("utf-8"), "text/csv")},
)
print("import csv:", r.status_code, r.json())
assert r.status_code == 200
assert r.json()["imported"] == 2
assert "Wallet Import" in r.json()["accounts_created"]

# Saldo dompet hasil import otomatis terisi (100k + 50k keluar = -150k)
with SessionLocal() as db:
    balances = {item["name"]: item["balance"] for item in wallet.balances(db)}
print("balances:", balances)
assert balances["Wallet Import"] == -150_000
assert balances["Dompet Uji"] == 200_000

# Halaman dompet menampilkan dompet baru + tombol sync
r = client.get("/accounts")
assert "Wallet Import" in r.text
assert "Sinkronkan saldo" in r.text

# Endpoint sync manual
r = client.post("/accounts/sync", follow_redirects=False)
print("sync:", r.status_code, r.headers.get("location"))
assert r.status_code == 303

# Transaksi baru lewat web -> saldo ikut berubah
r = client.post(
    "/transactions/create",
    data={
        "kind": "expense",
        "amount": "75000",
        "account_id": "1",
        "category_id": "",
        "merchant": "Kopi",
        "note": "",
        "occurred_at": "2026-02-03T09:00",
    },
    follow_redirects=False,
)
print("create transaction:", r.status_code)
assert r.status_code == 303

with SessionLocal() as db:
    balances = {item["name"]: item["balance"] for item in wallet.balances(db)}
print("balances after tx:", balances)
assert balances["Dompet Uji"] == 125_000

print("\nSMOKE WEB LULUS")
