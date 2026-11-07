"""Konfigurasi pytest bersama.

Semua tes memakai satu database SQLite sementara, dan isinya dibersihkan
sebelum setiap tes. Ini penting karena ``app.db`` membuat engine saat modul
di-import, jadi ``DATABASE_URL`` harus di-set sekali di sini — bukan di
masing-masing file tes (kalau tidak, file tes yang di-import belakangan akan
memakai database yang sama dengan sisa data tes sebelumnya).
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = Path(tempfile.gettempdir()) / "opencode" / "_pytest_catat.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["AUTO_MIGRATE"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ.setdefault("HERMES_API_TOKEN", "test-token")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    from app.db import engine
    from app.models import Base

    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean_database():
    """Kosongkan semua tabel sebelum tiap tes (urutan aman untuk FK)."""
    from sqlalchemy import delete

    from app.db import SessionLocal
    from app.models import (
        Account,
        AuditLog,
        Budget,
        Category,
        LoginAttempt,
        Merchant,
        Transaction,
        User,
        UserSession,
    )

    with SessionLocal() as db:
        for model in (
            Transaction,
            Budget,
            Account,
            Category,
            Merchant,
            AuditLog,
            UserSession,
            LoginAttempt,
            User,
        ):
            db.execute(delete(model))
        db.commit()

    yield
