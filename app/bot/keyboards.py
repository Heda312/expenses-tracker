"""Keyboard inline untuk draft transaksi."""

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.common import router
from app.models import Category


def _keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Simpan", callback_data=f"tx:ok:{transaction_id}"),
                InlineKeyboardButton(text="Ubah nominal", callback_data=f"tx:amt:{transaction_id}"),
            ],
            [
                InlineKeyboardButton(text="Ubah kategori", callback_data=f"tx:cat:{transaction_id}"),
                InlineKeyboardButton(text="Batal", callback_data=f"tx:no:{transaction_id}"),
            ],
        ]
    )

def _category_keyboard(transaction_id: int, categories: list[Category]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    last_kind = None

    for category in categories:
        if category.kind != last_kind:
            if current:
                rows.append(current)
                current = []
            label = "Pemasukan" if category.kind == "income" else "Pengeluaran"
            rows.append([InlineKeyboardButton(text=f"— {label} —", callback_data="tx:noop")])
            last_kind = category.kind
        current.append(
            InlineKeyboardButton(
                text=category.name,
                callback_data=f"tx:setcat:{transaction_id}:{category.id}",
            )
        )
        if len(current) == 2:
            rows.append(current)
            current = []

    if current:
        rows.append(current)

    rows.append([InlineKeyboardButton(text="Kembali", callback_data=f"tx:back:{transaction_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == "tx:noop")
async def callback_category_header(callback: CallbackQuery) -> None:
    await callback.answer()
