"""Webhook handler untuk Telegram Bot.

Alternative to polling yang lebih efisien dan production-ready.
"""

from fastapi import APIRouter, Request, Response
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from app.config import settings
from app.bot import router as bot_router

router = APIRouter()

# Initialize bot dan dispatcher untuk webhook
bot = Bot(token=settings.telegram_bot_token) if settings.telegram_bot_token else None
dp = Dispatcher()
if bot:
    dp.include_router(bot_router)


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Handle incoming updates dari Telegram via webhook."""
    if not bot:
        return Response(status_code=200)
    
    # Parse update dari request
    update_data = await request.json()
    update = Update(**update_data)
    
    # Process update
    await dp.feed_update(bot, update)
    
    return Response(status_code=200)


async def setup_webhook(webhook_url: str) -> bool:
    """Setup webhook untuk bot Telegram.
    
    Args:
        webhook_url: Public URL untuk webhook (e.g., https://yourdomain.com/webhook/telegram)
    
    Returns:
        True jika berhasil, False jika gagal
    """
    if not bot:
        return False
    
    try:
        # Delete existing webhook
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Set new webhook
        await bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query", "inline_query"],
            drop_pending_updates=True
        )
        
        # Verify webhook
        webhook_info = await bot.get_webhook_info()
        return webhook_info.url == webhook_url
    
    except Exception as e:
        print(f"Failed to setup webhook: {e}")
        return False


async def remove_webhook() -> bool:
    """Remove webhook dan kembali ke polling mode."""
    if not bot:
        return False
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        return True
    except Exception as e:
        print(f"Failed to remove webhook: {e}")
        return False
