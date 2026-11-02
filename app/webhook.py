"""Webhook handler untuk Telegram Bot.

Alternatif polling yang lebih efisien untuk production.
Aktif hanya kalau TELEGRAM_WEBHOOK_URL diisi.

Catatan penting: pembuatan Bot dan Dispatcher dilakukan lazy. Kalau dibuat
saat import, `bot_router` langsung menempel ke Dispatcher webhook sehingga
mode polling tidak bisa memakai router yang sama.
"""

import logging

from fastapi import APIRouter, Request, Response
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from app.config import settings
from app.bot import router as bot_router

logger = logging.getLogger(__name__)

router = APIRouter()

_bot: Bot | None = None
_dispatcher: Dispatcher | None = None


def get_bot() -> Bot | None:
    """Buat (sekali) Bot untuk mode webhook/pengelolaan webhook."""
    global _bot
    if _bot is None and settings.telegram_bot_token:
        _bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


def get_dispatcher() -> Dispatcher | None:
    """Buat Dispatcher webhook beserta router bot, hanya saat dibutuhkan."""
    global _dispatcher
    if get_bot() is None:
        return None
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(bot_router)
    return _dispatcher


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Terima update dari Telegram via webhook."""
    bot = get_bot()
    dispatcher = get_dispatcher()
    if not bot or not dispatcher:
        return Response(status_code=200)

    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dispatcher.feed_update(bot, update)
    except Exception:
        # Selalu balas 200 supaya Telegram tidak mengirim ulang terus-menerus.
        logger.exception("Gagal memproses update webhook Telegram")

    return Response(status_code=200)


async def setup_webhook(webhook_url: str) -> bool:
    """Daftarkan webhook ke Telegram. Return True kalau URL terpasang."""
    bot = get_bot()
    if not bot:
        return False

    try:
        await bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query", "inline_query"],
            drop_pending_updates=True,
        )
        info = await bot.get_webhook_info()
        return info.url == webhook_url
    except Exception:
        logger.exception("Gagal setup webhook: %s", webhook_url)
        return False


async def remove_webhook() -> bool:
    """Hapus webhook supaya bot bisa kembali ke mode polling."""
    bot = get_bot()
    if not bot:
        return False

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        return True
    except Exception:
        logger.warning("Gagal menghapus webhook.", exc_info=True)
        return False
