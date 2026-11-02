"""Uji cepat NLU bot pakai database sementara (tidak menyentuh data asli)."""

import asyncio
import os
import re
import tempfile
from datetime import timedelta
from pathlib import Path

TEMP_DB = Path(tempfile.gettempdir()) / "opencode" / "_test_nlu.db"
TEMP_DB.parent.mkdir(parents=True, exist_ok=True)
if TEMP_DB.exists():
    TEMP_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP_DB.as_posix()}"

from sqlalchemy import func, select  # noqa: E402

from app.bot import _answer_finance_question, _handle_info_query  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Account, Base, Budget, Category, Transaction  # noqa: E402
from app.services.dates import current_period, month_bounds, now_local, to_utc  # noqa: E402

Base.metadata.create_all(engine)

now = now_local()
with SessionLocal() as db:
    acc = Account(name="Cash", kind="cash", opening_balance=100_000)
    food = Category(name="Makanan", kind="expense", color="#f00")
    salary = Category(name="Gaji", kind="income", color="#0f0")
    db.add_all([acc, food, salary])
    db.flush()
    db.add(Budget(category_id=food.id, period=current_period(), amount=500_000))
    db.add_all(
        [
            Transaction(
                kind="expense",
                amount=25_000,
                category_id=food.id,
                account_id=acc.id,
                merchant="Indomaret",
                occurred_at=to_utc(now - timedelta(hours=1)),
                status="confirmed",
            ),
            Transaction(
                kind="expense",
                amount=15_000,
                category_id=food.id,
                account_id=acc.id,
                merchant="Indomaret",
                occurred_at=to_utc(now - timedelta(days=2)),
                status="confirmed",
            ),
            Transaction(
                kind="expense",
                amount=10_000,
                category_id=food.id,
                account_id=acc.id,
                merchant="Warung Bu Tini",
                occurred_at=to_utc(now - timedelta(days=3)),
                status="confirmed",
            ),
            Transaction(
                kind="income",
                amount=1_000_000,
                category_id=salary.id,
                account_id=acc.id,
                occurred_at=to_utc(now - timedelta(days=1)),
                status="confirmed",
            ),
        ]
    )
    db.commit()

FINANCE_CASES = [
    ("sisa saldo", "Sisa Saldo"),
    ("atur budget", "Atur Budget"),
    ("sisa budget", "Sisa Budget"),
    ("berapa pengeluaran bulan ini", "Pengeluaran"),
    ("berapa pemasukan minggu ini", "Pemasukan"),
    ("berapa untuk makanan minggu ini", "Makanan"),
    ("pengeluaran di indomaret", "Indomaret"),
]

INFO_CASES = [
    ("berapa kategori", "Info Kategori"),
    ("daftar kategori", "Daftar Kategori"),
    ("berapa dompet", "Daftar Akun"),
    ("daftar akun", "Daftar Akun"),
    ("berapa transaksi bulan ini", "Info Transaksi"),
    ("berapa transaksi total", "Info Transaksi"),
    ("atur budget", "Atur Budget"),
    ("daftar budget", "Budget"),
    ("pengeluaran per kategori", "Pengeluaran"),
    ("pengeluaran di indomaret", "Indomaret"),
]

TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return TAG_RE.sub("", text).strip().replace("\n", " | ")[:180]


def route_no_amount(question: str) -> str | None:
    """Tiru urutan routing handle_text untuk pesan tanpa nominal."""
    with SessionLocal() as db:
        info = asyncio.run(_handle_info_query(db, question.lower()))
    if info:
        return info
    return _answer_finance_question(question.lower())


def main() -> int:
    failed = 0

    print("=== FINANCE / INFO QUESTIONS ===")
    for q, expected in FINANCE_CASES:
        answer = route_no_amount(q)
        if not answer:
            failed += 1
            print(f"[MISS] {q!r} -> None")
            continue
        ok = expected.lower() in answer.lower()
        if not ok:
            failed += 1
        print(f"[{'OK' if ok else 'FAIL'}] {q!r} -> {clean(answer)}")

    print()
    print("=== INFO QUERIES ===")
    with SessionLocal() as db:
        for q, expected in INFO_CASES:
            answer = asyncio.run(_handle_info_query(db, q.lower()))
            if not answer:
                failed += 1
                print(f"[MISS] {q!r} -> None")
                continue
            ok = expected.lower() in answer.lower()
            if not ok:
                failed += 1
            print(f"[{'OK' if ok else 'FAIL'}] {q!r} -> {clean(answer)}")

    print()
    print("RESULT:", "ALL OK" if failed == 0 else f"{failed} query gagal")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        engine.dispose()
        if TEMP_DB.exists():
            TEMP_DB.unlink()
