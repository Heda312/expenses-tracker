"""Proses foto struk dan dokumen gambar."""

from aiogram import Bot, F
from aiogram.enums import ChatAction
from aiogram.types import Message

from app.bot.common import _allowed, logger, router
from app.bot.render import _render
from app.db import SessionLocal
from app.services import ingest


async def _process_image(message: Message, bot: Bot, image_bytes: bytes) -> None:
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    status = await message.reply("Membaca struk...")

    try:
        with SessionLocal() as db:
            transaction, data = await ingest.draft_from_photo(
                db,
                image_bytes,
                chat_id=message.chat.id,
                message_id=message.message_id,
                update_id=message.message_id,
            )

            if transaction is None:
                logger.warning(
                    "Gagal buat draft dari foto: lines=%s confidence=%s merchant=%s amount=%s",
                    len(data.raw_text.splitlines()) if data.raw_text else 0,
                    data.confidence,
                    data.merchant,
                    data.amount,
                )
                await status.edit_text(
                    "Struk belum bisa dibaca. Coba foto lebih terang dan tegak, "
                    "atau kirim sebagai file JPG/PNG. Bisa juga tulis manual: makan 35rb"
                )
                return

            text, keyboard = _render(db, transaction)
        await status.edit_text(text, reply_markup=keyboard)
    except Exception as exc:
        logger.exception("Error proses foto")
        await status.edit_text(f"Gagal memproses gambar: {exc}")

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot) -> None:
    if not _allowed(message.chat.id):
        return
    photo = message.photo[-1]
    try:
        file = await bot.get_file(photo.file_id)
        stream = await bot.download_file(file.file_path)
        await _process_image(message, bot, stream.read())
    except Exception:
        logger.exception("Gagal mengunduh foto Telegram")
        await message.reply("Foto gagal diunduh. Coba kirim ulang.")

@router.message(F.document)
async def handle_image_document(message: Message, bot: Bot) -> None:
    if not _allowed(message.chat.id) or not message.document:
        return
    mime = message.document.mime_type or ""
    name = (message.document.file_name or "").lower()
    if not (mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"))):
        await message.reply("Kirim file gambar JPG, PNG, WEBP, BMP, atau TIFF.")
        return
    try:
        file = await bot.get_file(message.document.file_id)
        stream = await bot.download_file(file.file_path)
        await _process_image(message, bot, stream.read())
    except Exception:
        logger.exception("Gagal mengunduh dokumen Telegram")
        await message.reply("Gambar gagal diunduh. Coba kirim ulang.")
