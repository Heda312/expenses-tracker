"""Mengubah input mentah (foto / teks) menjadi transaksi berstatus "pending".

Transaksi pending belum masuk laporan sampai pengguna menekan tombol
Simpan di Telegram atau tombol simpan di website.
"""

import asyncio
import logging
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, Transaction, utcnow
from app.services import classify, ocr, receipt
from app.services.dates import parse_date, to_local_datetime
from app.services.money import extract_amount

logger = logging.getLogger(__name__)

INCOME_WORDS = re.compile(r"\b(gaji|bonus|thr|refund|pemasukan|masuk)\b", re.IGNORECASE)


def _active_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.archived.is_(False))).all())


def _pick_account(db: Session, text: str = "") -> Account | None:
    """Tebak dompet dari kata kunci, kalau tidak ada pakai dompet pertama."""
    accounts = _active_accounts(db)
    if not accounts:
        return None
    lowered = text.lower()
    for account in accounts:
        if account.name.lower() in lowered:
            return account
    return accounts[0]


def _save_image(image_bytes: bytes, suffix: str = ".jpg") -> str:
    name = f"{uuid.uuid4().hex}{suffix}"
    path = Path(settings.upload_dir) / name
    path.write_bytes(image_bytes)
    return f"uploads/{name}"


def _is_duplicate(db: Session, update_id: int | None) -> bool:
    if update_id is None:
        return False
    existing = db.scalar(
        select(Transaction.id).where(Transaction.telegram_update_id == update_id)
    )
    return existing is not None


async def draft_from_photo(
    db: Session,
    image_bytes: bytes,
    chat_id: int | None = None,
    message_id: int | None = None,
    update_id: int | None = None,
) -> tuple[Transaction | None, receipt.ReceiptData]:
    """Foto struk -> transaksi pending."""
    if _is_duplicate(db, update_id):
        return None, receipt.ReceiptData()

    image_path = _save_image(image_bytes)

    try:
        # OCR memakan CPU, jadi wajib dijalankan di thread terpisah.
        lines = await asyncio.to_thread(ocr.read_lines, image_bytes)
        logger.info("OCR lines: %s", [l.get("text") for l in lines][:15])
    except ocr.OcrError as exc:
        logger.warning("OCR gagal: %s", exc)
        return None, receipt.ReceiptData()

    data = receipt.parse_receipt(lines)
    logger.info(
        "Hasil parse: amount=%s merchant=%s date=%s conf=%s",
        data.amount,
        data.merchant,
        data.date,
        data.confidence,
    )
    account = _pick_account(db, data.raw_text)
    if account is None:
        return None, data

    occurred_at = to_local_datetime(data.date) if data.date else utcnow()
    kind = "income" if INCOME_WORDS.search(data.raw_text or "") else "expense"
    category_id, category_source = await classify.classify_category(db, data.merchant, data.raw_text, kind=kind)

    transaction = Transaction(
        kind=kind,
        amount=data.amount or 0,
        account_id=account.id,
        category_id=category_id,
        merchant=(data.merchant or None),
        note=None,
        occurred_at=occurred_at,
        source="telegram",
        status="pending",
        confidence=data.confidence,
        raw_text=data.raw_text[:4000],
        image_path=image_path,
        category_source=category_source,
        telegram_chat_id=chat_id,
        telegram_message_id=message_id,
        telegram_update_id=update_id,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction, data


async def draft_from_text(
    db: Session,
    text: str,
    chat_id: int | None = None,
    message_id: int | None = None,
    update_id: int | None = None,
) -> Transaction | None:
    """Teks bebas -> transaksi pending."""
    if _is_duplicate(db, update_id):
        return None

    amount = extract_amount(text)
    if not amount:
        return None

    account = _pick_account(db, text)
    if account is None:
        return None

    kind = "income" if INCOME_WORDS.search(text) else "expense"
    parsed_date = parse_date(text)
    occurred_at = to_local_datetime(parsed_date) if parsed_date else utcnow()

    category_id, category_source = await classify.classify_category(db, None, text, kind=kind)

    transaction = Transaction(
        kind=kind,
        amount=amount,
        account_id=account.id,
        category_id=category_id,
        merchant=None,
        note=text[:500],
        occurred_at=occurred_at,
        source="telegram",
        status="pending",
        confidence=1.0 if parsed_date else 0.8,
        raw_text=text[:4000],
        category_source=category_source,
        telegram_chat_id=chat_id,
        telegram_message_id=message_id,
        telegram_update_id=update_id,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction
