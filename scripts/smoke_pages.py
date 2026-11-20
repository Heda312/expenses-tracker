"""Smoke test semua halaman utama pakai TestClient (tanpa server terpisah).

Jalankan dengan DATABASE_URL sementara supaya tidak menyentuh data asli:
    DATABASE_URL=sqlite:////tmp/smoke.db PYTHONPATH=. python scripts/smoke_pages.py

TestClient dipakai sebagai context manager agar lifespan aplikasi (migrasi
database + seed) ikut berjalan, sehingga DB baru pun langsung siap.
"""

import traceback

from fastapi.testclient import TestClient

from app.main import app

PAGES = [
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


def main() -> int:
    failed = 0
    with TestClient(app, raise_server_exceptions=False) as client:
        # Daftar dulu kalau DB masih kosong, lalu login.
        r = client.post(
            "/register",
            data={
                "username": "admin",
                "password": "adminpassword123",
                "confirm_password": "adminpassword123",
            },
            follow_redirects=False,
        )
        print("REGISTER:", r.status_code, r.headers.get("location", ""))
        r = client.post(
            "/login",
            data={"username": "admin", "password": "adminpassword123"},
            follow_redirects=False,
        )
        print("LOGIN:", r.status_code, r.headers.get("location", ""))

        for page in PAGES:
            try:
                r = client.get(page, follow_redirects=False)
                status = r.status_code
                loc = r.headers.get("location", "")
                body_ok = "Internal Server Error" not in r.text
                # register/login redirect ke "/" kalau sudah login, itu wajar.
                ok = body_ok and status < 500
                if not ok:
                    failed += 1
                print(f"{page:60} -> {status} {loc} {'OK' if ok else 'FAIL'}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"{page:60} -> EXCEPTION {exc}")
                traceback.print_exc()

    print()
    print("RESULT:", "ALL OK" if failed == 0 else f"{failed} halaman gagal")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())