"""Titik masuk aplikasi FastAPI.

Menjalankan:
    uvicorn app.main:app --reload
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import SessionLocal
from app.routers import (
    accounts,
    api,
    auth,
    budgets,
    categories,
    dashboard,
    export,
    ocr,
    settings_page,
    transactions,
)
from app.security import RedirectToLogin, require_user
from app.seed import ensure_seed
from app import webhook
from app.models import Base
from app.db import engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _run_migrations() -> None:
    """Jalankan migrasi Alembic; kalau gagal, pastikan tabel dasar tetap ada."""
    from app.schema_patch import ensure_columns

    if not settings.auto_migrate:
        logger.info("AUTO_MIGRATE=false, migrasi dilewati.")
        ensure_columns()
        return
    try:
        from alembic import command
        from alembic.config import Config

        alembic_config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
        # Jangan biarkan Alembic menimpa konfigurasi logging aplikasi.
        alembic_config.attributes["configure_logger"] = False
        command.upgrade(alembic_config, "head")
        logger.info("Migrasi database selesai.")
    except Exception:
        # Jangan matikan aplikasi hanya karena migrasi. Tabel yang sudah ada
        # tetap bisa dipakai; create_all menambal tabel yang belum dibuat.
        logger.exception("Migrasi database gagal, fallback ke create_all")
        Base.metadata.create_all(engine)
    finally:
        # Pastikan kolom baru tetap ada walau migrasi dilewati/gagal.
        ensure_columns()




@asynccontextmanager
async def lifespan(_app: FastAPI):
    _run_migrations()

    # Isi kategori & dompet default saat pertama kali dijalankan.
    with SessionLocal() as db:
        ensure_seed(db)
        # Hitung ulang saldo dompet dari transaksi yang sudah ada, supaya
        # cache saldo tidak pernah basi setelah upgrade.
        from app.services import wallet

        wallet.sync_balances(db)

    bot_task = None
    if settings.telegram_bot_token:
        from app.bot import start_bot

        webhook_url = settings.telegram_webhook_url.strip()

        if webhook_url:
            # Mode webhook: Telegram mengirim update ke endpoint /webhook/telegram.
            try:
                ok = await webhook.setup_webhook(webhook_url)
                logger.info("Bot Telegram memakai webhook: %s (%s)", webhook_url, "ok" if ok else "gagal")
            except Exception:
                logger.exception("Gagal setup webhook Telegram")
        else:
            # Mode polling: pastikan webhook lama dihapus agar tidak konflik.
            try:
                await webhook.remove_webhook()
            except Exception:
                logger.warning("Gagal menghapus webhook lama, lanjut polling.", exc_info=True)

            async def _start_bot_wrapper():
                try:
                    await start_bot()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Bot Telegram berhenti tak terduga")

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


ERROR_PAGE = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Terjadi Kesalahan</title>
<style>
  body {{ font-family: system-ui, sans-serif; background:#0f172a; color:#e2e8f0;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
  .card {{ background:#1e293b; padding:40px; border-radius:16px; max-width:460px; text-align:center; }}
  h1 {{ font-size:20px; margin:0 0 12px; }}
  p {{ color:#94a3b8; line-height:1.6; margin:0 0 24px; }}
  a {{ color:#38bdf8; text-decoration:none; font-weight:600; }}
</style>
</head>
<body>
  <div class="card">
    <h1>😵 Terjadi kesalahan</h1>
    <p>Permintaan ini gagal diproses. Data kamu tetap aman.
       Coba muat ulang halaman atau kembali ke dashboard.</p>
    <a href="/">← Kembali ke Dashboard</a>
  </div>
</body>
</html>"""


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Tampilkan halaman error yang ramah, bukan traceback mentah."""
    logger.exception("Unhandled error pada %s %s", request.method, request.url.path)

    wants_json = (
        request.url.path.startswith(("/webhook", "/api", "/v1", "/health"))
        or "application/json" in request.headers.get("accept", "")
    )
    if wants_json:
        return JSONResponse({"error": "internal_server_error"}, status_code=500)

    return HTMLResponse(ERROR_PAGE, status_code=500)


@app.exception_handler(RedirectToLogin)
async def _redirect_to_login(request: Request, _exc: RedirectToLogin):
    # Check if database has any users
    with SessionLocal() as db:
        from sqlalchemy import select
        from app.models import User
        has_users = db.scalar(select(User.id).limit(1)) is not None
    
    # If no users exist and not already on register page, redirect to register
    if not has_users and not request.url.path.startswith("/register"):
        return RedirectResponse("/register", status_code=303)
    
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
app.include_router(categories.router)
app.include_router(budgets.router)
app.include_router(export.router)
app.include_router(ocr.router)
app.include_router(settings_page.router)
app.include_router(api.router)
app.include_router(webhook.router)
