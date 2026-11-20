"""Handler FSM EditAmount: input nominal baru untuk draft transaksi.

Dipisah dari transactions.py agar urutan registrasi message handler sama
dengan app/bot.py asli (terdaftar setelah laporan periodik, sebelum foto).
"""

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.common import EditAmount, _allowed, router
from app.bot.render import _render
from app.db import SessionLocal
from app.models import Transaction
from app.services import wallet
from app.services.money import parse_amount


@router.message(EditAmount.waiting)
async def handle_new_amount(message: Message, state: FSMContext) -> None:
    if not _allowed(message.chat.id):
        return

    amount = parse_amount(message.text)
    if not amount or amount <= 0:
        await message.reply("Nominal tidak dikenali. Contoh: 47500 atau 47.500")
        return

    data = await state.get_data()
    await state.clear()

    with SessionLocal() as db:
        transaction = db.get(Transaction, data.get("tx_id"))
        if transaction is None or transaction.deleted_at is not None:
            await message.reply("Transaksi sudah tidak ada.")
            return

        transaction.amount = amount
        db.commit()
        wallet.sync_balances(db)

        text, keyboard = _render(db, transaction)

    await message.reply(text, reply_markup=keyboard)
