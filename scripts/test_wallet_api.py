"""Uji alur dompet dinamis + import + API Hermes pada database sementara."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEMP = Path(tempfile.gettempdir()) / "opencode" / "_wallet_api_test.db"
TEMP.parent.mkdir(parents=True, exist_ok=True)
if TEMP.exists():
    TEMP.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP.as_posix()}"
os.environ["HERMES_API_TOKEN"] = "test-token-123"
os.environ["AUTO_MIGRATE"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, Base, Transaction  # noqa: E402
from app.services import wallet  # noqa: E402

Base.metadata.create_all(engine)

client = TestClient(app, raise_server_exceptions=True)
headers = {"Authorization": "Bearer test-token-123"}

print("1) health:", client.get("/api/v1/health").json())

# --- Buat dompet lewat API ---
r = client.post("/api/v1/accounts", json={"name": "BCA", "opening_balance": "1.000.000"}, headers=headers)
print("2) create account:", r.status_code, r.json())
assert r.status_code == 201

# --- Transaksi expense -> saldo turun ---
r = client.post(
    "/api/v1/transactions",
    json={"kind": "expense", "amount": "250rb", "account": "BCA", "category": "Makanan", "merchant": "Indomaret"},
    headers=headers,
)
print("3) create expense:", r.status_code, r.json()["amount"], r.json()["account"], r.json()["category"])
assert r.status_code == 201
tx_id = r.json()["id"]

r = client.get("/api/v1/accounts", headers=headers)
bca = [a for a in r.json()["accounts"] if a["name"] == "BCA"][0]
print("4) saldo setelah expense:", bca["balance"], "count:", bca["transaction_count"])
assert bca["balance"] == 750_000

# --- Income -> saldo naik ---
r = client.post(
    "/api/v1/transactions",
    json={"kind": "income", "amount": 2_000_000, "account": "BCA", "category": "Gaji"},
    headers=headers,
)
print("5) create income:", r.status_code)
r = client.get("/api/v1/accounts", headers=headers)
bca = [a for a in r.json()["accounts"] if a["name"] == "BCA"][0]
print("6) saldo setelah income:", bca["balance"])
assert bca["balance"] == 2_750_000

# --- Update transaksi -> saldo ikut berubah ---
r = client.patch(f"/api/v1/transactions/{tx_id}", json={"amount": 500_000}, headers=headers)
print("7) update amount:", r.status_code, r.json()["amount"])
r = client.get("/api/v1/accounts", headers=headers)
bca = [a for a in r.json()["accounts"] if a["name"] == "BCA"][0]
print("8) saldo setelah update:", bca["balance"])
assert bca["balance"] == 2_500_000

# --- Delete transaksi -> saldo kembali ---
r = client.delete(f"/api/v1/transactions/{tx_id}", headers=headers)
print("9) delete:", r.status_code)
r = client.get("/api/v1/accounts", headers=headers)
bca = [a for a in r.json()["accounts"] if a["name"] == "BCA"][0]
print("10) saldo setelah delete:", bca["balance"])
assert bca["balance"] == 3_000_000

# --- Transfer antar dompet ---
client.post("/api/v1/accounts", json={"name": "GoPay", "kind": "ewallet"}, headers=headers)
r = client.post(
    "/api/v1/transactions",
    json={"kind": "transfer", "amount": 300_000, "account": "BCA", "to_account": "GoPay"},
    headers=headers,
)
print("11) transfer:", r.status_code, r.json().get("to_account"))
r = client.get("/api/v1/accounts", headers=headers)
balances = {a["name"]: a["balance"] for a in r.json()["accounts"]}
print("12) saldo setelah transfer:", balances)
assert balances["BCA"] == 2_700_000
assert balances["GoPay"] == 300_000

# --- Kategori CRUD ---
r = client.post("/api/v1/categories", json={"name": "Transport", "kind": "expense"}, headers=headers)
print("13) create category:", r.status_code, r.json())
cat_id = r.json()["id"]
r = client.patch(f"/api/v1/categories/{cat_id}", json={"name": "Transportasi"}, headers=headers)
print("14) update category:", r.status_code, r.json()["name"])
r = client.delete(f"/api/v1/categories/{cat_id}", headers=headers)
print("15) delete category:", r.status_code)

# --- Import CSV: dompet otomatis dibuat dari kolom Dompet ---
csv_text = (
    "Tanggal, Nominal, Kategori, Merchant, Dompet\n"
    "2026-01-05, 150000, Makanan, Warung, Dompet Baru\n"
    "2026-01-06, 250000, Transport, Grab, Dompet Baru\n"
    "2026-01-07, 900000, Gaji, Kantor, Rekening Gaji\n"
)
r = client.post("/api/v1/import/csv/text", json={"csv": csv_text}, headers=headers)
print("16) import:", r.status_code, r.json()["imported"], r.json()["accounts_created"])
assert r.status_code == 201
assert set(r.json()["accounts_created"]) == {"Dompet Baru", "Rekening Gaji"}

r = client.get("/api/v1/accounts", headers=headers)
balances = {a["name"]: a["balance"] for a in r.json()["accounts"]}
print("17) saldo setelah import:", balances)
assert balances["Dompet Baru"] == -400_000
assert balances["Rekening Gaji"] == 900_000

# --- Cache saldo tersimpan di DB dan sinkron ---
with SessionLocal() as db:
    for account in db.scalars(select(Account)).all():
        live = wallet.balances_map(db).get(account.id, 0)
        assert account.cached_balance == live, (account.name, account.cached_balance, live)
    print("18) cache saldo sinkron untuk semua dompet")

# --- Auth wajib ---
r = client.get("/api/v1/accounts")
print("19) tanpa token:", r.status_code)
assert r.status_code == 401

r = client.get("/api/v1/accounts", headers={"Authorization": "Bearer salah"})
print("20) token salah:", r.status_code)
assert r.status_code == 401

# --- Transaksi pending tidak memengaruhi saldo ---
r = client.post(
    "/api/v1/transactions",
    json={"kind": "expense", "amount": 100_000, "account": "GoPay", "status": "pending"},
    headers=headers,
)
print("21) pending:", r.status_code, r.json()["status"])
r = client.get("/api/v1/accounts", headers=headers)
gopay = [a for a in r.json()["accounts"] if a["name"] == "GoPay"][0]
print("22) saldo GoPay (pending diabaikan):", gopay["balance"])
assert gopay["balance"] == 300_000

print("\nSEMUA TES LULUS")
