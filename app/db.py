"""Koneksi database dan dependency FastAPI."""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# check_same_thread=False wajib untuk SQLite karena satu koneksi bisa
# dipakai dari thread berbeda (bot + web berjalan di proses yang sama).
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """WAL bikin baca dan tulis bisa jalan bersamaan.

    Ini penting karena bot dan website memakai database yang sama.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    """Dependency FastAPI: satu session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
