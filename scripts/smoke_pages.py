"""Smoke test semua halaman utama pakai TestClient (tanpa server terpisah)."""

import traceback

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# login
r = client.post(
    "/login",
    data={"username": "admin", "password": "adminpassword123"},
    follow_redirects=False,
)
print("LOGIN:", r.status_code, dict(r.headers).get("location"))

pages = [
    "/",
    "/?period_type=week",
    "/?period_type=month&period=2026-10",
    "/?period_type=year&period=2026",
    "/?period_type=custom&start=2026-01-01&end=2026-01-31",
    "/?period_type=all",
    "/transactions",
    "/transactions?period_type=week",
    "/transactions?period_type=month&period=2026-10",
    "/transactions?period_type=year&period=2026",
    "/transactions?period_type=custom&start=2026-01-01&end=2026-01-31",
    "/transactions?period_type=all",
    "/accounts",
    "/categories",
    "/budgets",
    "/settings",
    "/api/categories",
    "/register",
    "/login",
]

failed = 0
for p in pages:
    try:
        r = client.get(p, follow_redirects=False)
        status = r.status_code
        loc = r.headers.get("location", "")
        body_ok = "Internal Server Error" not in r.text
        # register/login redirect ke "/" kalau sudah login, itu wajar.
        ok = body_ok and (status < 500)
        if not ok:
            failed += 1
        print(f"{p:20} -> {status} {loc} {'OK' if ok else 'FAIL'}")
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print(f"{p:20} -> EXCEPTION {exc}")
        traceback.print_exc()

print()
print("RESULT:", "ALL OK" if failed == 0 else f"{failed} halaman gagal")
raise SystemExit(1 if failed else 0)
