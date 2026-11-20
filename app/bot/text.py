"""Router pesan teks natural-language (handle_text)."""

from aiogram import F
from aiogram.types import Message

from app.bot.budgets import _handle_budget_set
from app.bot.categories import (
    _handle_add_category,
    _handle_delete_category,
    _handle_rename_category,
)
from app.bot.common import _allowed, _budget_edit_state, router
from app.bot.queries import _answer_finance_question, _handle_info_query
from app.bot.render import (
    HELP_TEXT,
    _financial_summary,
    _render,
    _render_budget_preview,
)
from app.db import SessionLocal
from app.services import ingest
from app.services.money import extract_amount


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    if not _allowed(message.chat.id):
        return

    text = (message.text or "").strip()
    question = text.lower()
    
    # Check if user sedang edit nominal budget
    chat_id = message.chat.id
    if chat_id in _budget_edit_state:
        amount = extract_amount(text)
        if amount:
            category_id = _budget_edit_state[chat_id]["category_id"]
            del _budget_edit_state[chat_id]
            
            with SessionLocal() as db:
                preview_text, keyboard = _render_budget_preview(db, category_id, amount)
            
            await message.reply(preview_text, reply_markup=keyboard)
            return
        else:
            await message.reply("❌ Nominal tidak valid. Coba lagi atau /cancel")
            return
    
    # CRUD Kategori: tambah, hapus, ubah
    if any(word in question for word in ("tambah kategori", "kategori baru", "buat kategori")):
        with SessionLocal() as db:
            await _handle_add_category(db, text, message)
        return
    
    if any(word in question for word in ("hapus kategori", "delete kategori")):
        with SessionLocal() as db:
            await _handle_delete_category(db, text, message)
        return
    
    if "ubah kategori" in question and "jadi" in question:
        with SessionLocal() as db:
            await _handle_rename_category(db, text, message)
        return
    
    # Check if setting budget: "budget makanan 2jt", "atur budget transportasi 500rb"
    if any(word in question for word in ("budget", "anggaran")):
        amount = extract_amount(text)
        if amount:
            # Parse budget command
            with SessionLocal() as db:
                await _handle_budget_set(db, text, amount, message)
            return
    
    # Query info dan finance question HARUS sebelum draft transaksi
    # Check dulu apakah ini pertanyaan (tanpa nominal) atau transaksi (ada nominal)
    has_amount = extract_amount(text) is not None
    
    # Jika tidak ada nominal, prioritaskan sebagai query/pertanyaan
    if not has_amount:
        # Query info - "berapa kategori", "total transaksi", "kategori apa saja"
        with SessionLocal() as db:
            query_result = await _handle_info_query(db, question)
            if query_result:
                await message.reply(query_result, parse_mode="HTML")
                return
        
        # Finance questions - "berapa saldo", "pengeluaran bulan ini"
        finance_answer = _answer_finance_question(question)
        if finance_answer:
            await message.reply(finance_answer)
            return
        
        # Ringkasan kondisi keuangan
        if any(word in question for word in ("kondisi keuangan", "ringkas", "keuangan saya", "cashflow")):
            await message.reply(_financial_summary())
            return
        
        # Default: bantu user jika tidak mengerti
        if any(word in question for word in ("bantu", "help", "tutorial", "cara", "apa")):
            await message.reply(HELP_TEXT)
            return
    
    # Jika ada nominal DAN bukan pertanyaan budget, masuk ke draft transaksi
    with SessionLocal() as db:
        transaction = await ingest.draft_from_text(
            db,
            text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            update_id=message.message_id,
        )

        if transaction is None:
            await message.reply(
                "Nominal tidak ditemukan. Tulis seperti: makan siang 35rb"
            )
            return

        text, keyboard = _render(db, transaction)

    await message.reply(text, reply_markup=keyboard)
