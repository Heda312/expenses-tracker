"""Penambal skema ringan untuk kolom baru.

Alembic adalah jalur utama, tapi kalau migrasi gagal (misalnya database lama
dibuka dengan AUTO_MIGRATE=false) aplikasi tetap harus jalan. Fungsi di sini
hanya menambah kolom yang belum ada, tanpa mengubah data.
"""

import logging

from sqlalchemy import inspect, text

from app.db import engine

logger = logging.getLogger(__name__)

# (tabel, kolom, DDL tipe + default)
COLUMNS = (
    ("accounts", "cached_balance", "INTEGER NOT NULL DEFAULT 0"),
    ("accounts", "balance_updated_at", "DATETIME"),
)


def ensure_columns() -> None:
    """Tambah kolom yang hilang di database yang belum dimigrasi."""
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    except Exception:
        logger.warning("Tidak bisa membaca skema database, penambal dilewati.", exc_info=True)
        return

    for table, column, ddl in COLUMNS:
        if table not in tables:
            continue
        existing = {item["name"] for item in inspector.get_columns(table)}
        if column in existing:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            logger.info("Kolom %s.%s ditambahkan otomatis.", table, column)
        except Exception:
            logger.warning("Gagal menambah kolom %s.%s.", table, column, exc_info=True)
