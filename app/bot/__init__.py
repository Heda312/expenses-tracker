"""Bot Telegram.

Alur: kirim foto struk atau tulis transaksi -> bot menampilkan draft ->
pengguna menekan Simpan / Ubah / Batal. Tidak ada yang masuk laporan
sebelum dikonfirmasi.
"""

# ruff: noqa: I001  (urutan import handler = urutan registrasi, tidak boleh di-sort)

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# Modul handler mendaftarkan handler ke router bersama saat di-import.
# URUTAN import di bawah ini WAJIB sama dengan urutan registrasi handler
# pada app/bot.py asli (aiogram mencocokkan handler sesuai urutan registrasi).
from app.bot import keyboards  # noqa: F401
from app.bot import queries  # noqa: F401
from app.bot import budgets  # noqa: F401
from app.bot import categories  # noqa: F401
from app.bot import transactions  # noqa: F401
from app.bot import reports  # noqa: F401
from app.bot import edit_amount  # noqa: F401
from app.bot import media  # noqa: F401
from app.bot import text  # noqa: F401
from app.bot import delete_flow  # noqa: F401
from app.bot import categories_callbacks  # noqa: F401
from app.bot import budgets_callbacks  # noqa: F401
from app.bot.common import logger, router
from app.config import settings

bot_instance: Bot | None = None


async def start_bot() -> None:
    """Dipanggil dari lifespan FastAPI."""
    global bot_instance
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    bot_instance = bot
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)

    if settings.telegram_chat_id is None:
        logger.warning("TELEGRAM_ALLOWED_CHAT_ID belum diisi, bot akan mengabaikan semua pesan.")

    try:
        me = await bot.get_me()
        logger.info("Bot @%s aktif.", me.username)
        await dispatcher.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Bot Telegram berhenti: %s", exc)
    finally:
        bot_instance = None
        await bot.session.close()
