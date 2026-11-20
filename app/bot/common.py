"""State dan utilitas bersama untuk package bot Telegram."""

import logging

from aiogram import Router
from aiogram.fsm.state import State, StatesGroup

from app.config import settings

# Nama logger dipertahankan "app.bot" agar output log tidak berubah.
logger = logging.getLogger("app.bot")
router = Router()


# Budget edit state: {chat_id: {"category_id": int}}
_budget_edit_state: dict[int, dict] = {}

class EditAmount(StatesGroup):
    waiting = State()

def _allowed(chat_id: int | None) -> bool:
    """Hanya satu chat yang boleh memakai bot ini."""
    allowed_id = settings.telegram_chat_id
    return allowed_id is not None and chat_id == allowed_id
