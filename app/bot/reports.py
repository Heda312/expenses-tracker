"""Laporan periodik: /pengeluaran /pemasukan /harian /mingguan /bulanan.

Dipisah dari queries.py agar urutan registrasi message handler sama dengan
app/bot.py asli (blok ini terdaftar setelah handler dokumen CSV).
"""

from aiogram.filters import Command
from aiogram.types import Message

from app.bot.common import _allowed, router
from app.db import SessionLocal
from app.services import ledger
from app.services.dates import current_period
from app.services.money import format_idr


@router.message(Command("pengeluaran", "pemasukan"))
async def handle_totals(message: Message) -> None:
    if not _allowed(message.chat.id):
        return
    with SessionLocal() as db:
        data = ledger.summary(db, current_period())
    key = "expense" if message.text.lower().startswith("/pengeluaran") else "income"
    label = "Pengeluaran" if key == "expense" else "Pemasukan"
    await message.answer(f"{label} bulan ini: <b>{format_idr(data[key])}</b>")

async def _period_report(message: Message, scope: str) -> None:
    if not _allowed(message.chat.id):
        return
    with SessionLocal() as db:
        data = ledger.named_range_summary(db, scope)
    await message.answer(
        f"<b>Ringkasan {data['label']}</b>\n"
        f"Pemasukan: <b>{format_idr(data['income'])}</b>\n"
        f"Pengeluaran: <b>{format_idr(data['expense'])}</b>\n"
        f"Cashflow: <b>{format_idr(data['net'])}</b>\n"
        f"Transaksi: {data['count']}"
    )

@router.message(Command("harian"))
async def handle_daily(message: Message) -> None:
    await _period_report(message, "day")

@router.message(Command("mingguan"))
async def handle_weekly(message: Message) -> None:
    await _period_report(message, "week")

@router.message(Command("bulanan"))
async def handle_monthly(message: Message) -> None:
    await _period_report(message, "month")
