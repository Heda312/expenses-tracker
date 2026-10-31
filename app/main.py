"""Titik masuk aplikasi FastAPI.

Menjalankan:
    uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import SessionLocal
from app.routers import accounts, auth, budgets, dashboard, export, ocr, settings_page, transactions
from app.security import RedirectToLogin, require_user
from app.seed import ensure_seed

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Pastikan schema tersedia sebelum route setup/login membaca tabel users.
    # Docker menjalankan migration sebelum Uvicorn, tetapi guard ini membuat
    # local/dev start tetap aman saat database baru masih kosong.
    try:
        from alembic import command
        from alembic.config import Config

        alembic_config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
        command.upgrade(alembic_config, "head")
    except Exception:
        logger.exception("Migrasi database gagal saat startup")
        raise

    # Isi kategori & dompet default saat pertama kali dijalankan.
    with SessionLocal() as db:
        ensure_seed(db)

    bot_task = None
    if settings.telegram_bot_token:
        from app.bot import start_bot

        async def _start_bot_wrapper():
            try:
                await start_bot()
            except asyncio.CancelledError:
                pass

        bot_task = asyncio.create_task(_start_bot_wrapper())
        logger.info("Bot Telegram dijalankan (polling).")

    try:
        yield
    finally:
        if bot_task:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(RedirectToLogin)
async def _redirect_to_login(_request: Request, _exc: RedirectToLogin):
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
def openai_models():
    """Dummy endpoint buat menghindari 404 dari client yang auto-discover."""
    return {"object": "list", "data": []}


@app.get("/uploads/{filename}")
def uploaded_file(filename: str, _user=Depends(require_user)):
    """Foto struk hanya bisa dibuka oleh pengguna yang sudah login."""
    safe_name = Path(filename).name
    path = Path(settings.upload_dir) / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    return FileResponse(path)


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(budgets.router)
app.include_router(export.router)
app.include_router(ocr.router)
app.include_router(settings_page.router)
