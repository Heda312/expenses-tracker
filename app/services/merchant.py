"""Normalisasi nama merchant dan pencocokan dengan ingatan merchant.

Tujuan: nama merchant hasil OCR hampir tidak pernah sama persis
("INDOMARET 1234 JL SUDIRMAN" vs "INDOMARFT"), jadi harus dinormalisasi
dulu sebelum dicari di tabel merchants.
"""

import re

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Merchant

# Kata yang tidak membantu identifikasi merchant.
NOISE_WORDS = {
    "JL", "JLN", "JALAN", "NO", "RUKO", "BLOK", "KAV", "KAVLING", "LT",
    "TELP", "TLP", "NPWP", "KASIR", "INVOICE", "INV", "STRUK", "NOTA",
    "CABANG", "CAB", "TOKO", "UD", "CV", "PT", "KOTA", "KEC", "KEL",
}

FUZZY_THRESHOLD = 88  # 0-100, makin tinggi makin ketat


def normalize_merchant(raw: str | None) -> str:
    """Bersihkan nama merchant jadi bentuk yang stabil."""
    if not raw:
        return ""

    text = raw.upper()
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\b\d+\b", " ", text)  # buang kode toko / nomor

    words = [word for word in text.split() if word not in NOISE_WORDS and len(word) > 1]
    return " ".join(words[:3])


def find_exact(db: Session, raw_merchant: str | None) -> Merchant | None:
    """Cocok persis dengan alias yang pernah disimpan."""
    alias = normalize_merchant(raw_merchant)
    if not alias:
        return None
    return db.scalar(select(Merchant).where(Merchant.alias == alias))


def find_fuzzy(db: Session, raw_merchant: str | None) -> tuple[Merchant | None, int]:
    """Cocok mirip, untuk menangani typo hasil OCR. Hasil: (merchant, skor)."""
    alias = normalize_merchant(raw_merchant)
    if not alias:
        return None, 0

    rows = db.scalars(select(Merchant)).all()
    if not rows:
        return None, 0

    match = process.extractOne(
        alias,
        {row.alias: row for row in rows},
        scorer=fuzz.token_set_ratio,
        score_cutoff=FUZZY_THRESHOLD,
    )
    if not match:
        return None, 0

    _alias, score, row = match
    return row, int(score)


def remember_merchant(
    db: Session,
    raw_merchant: str | None,
    category_id: int | None,
    canonical: str | None = None,
) -> Merchant | None:
    """Simpan/ubah ingatan merchant setelah pengguna mengonfirmasi kategori."""
    alias = normalize_merchant(raw_merchant)
    if not alias or not category_id:
        return None

    existing = db.scalar(select(Merchant).where(Merchant.alias == alias))
    if existing is None:
        existing = Merchant(
            alias=alias,
            canonical=(canonical or raw_merchant or alias).strip()[:120],
            category_id=category_id,
            hits=1,
        )
        db.add(existing)
    else:
        existing.category_id = category_id
        existing.hits += 1
    return existing
