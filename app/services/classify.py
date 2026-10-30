"""Penentu kategori transaksi, berlapis dari yang paling murah.

Urutan:
  1. ingatan merchant (cocok persis)   -> 0 ms
  2. aturan keyword                    -> 0 ms
  3. ingatan merchant (mirip/fuzzy)    -> 1 ms
  4. LLM lokal (kalau diaktifkan)      -> 0.3-0.8 s
  5. "Lainnya"

Semakin sering dipakai, lapis 1 dan 3 semakin banyak terisi sehingga
LLM makin jarang dipanggil.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Category
from app.services import llm
from app.services.merchant import find_exact, find_fuzzy

# (pola, nama kategori). Urutan menentukan prioritas.
CATEGORY_RULES: list[tuple[str, str]] = [
    (r"pln|listrik|token|pdam|\bair\b|indihome|internet|wifi|pulsa|paket data|telkomsel|indosat|\bxl\b|\btri\b|bpjs|kos|sewa|cicilan|kartu kredit|iuran", "Tagihan"),
    (r"parkir|bensin|pertamax|pertalite|solar|gojek|grab|ojek|taksi|taxi|transjakarta|\bkrl\b|\bmrt\b|\bbus\b|travel|\btol\b|bengkel|tiket|bandara", "Transportasi"),
    (r"apotek|apotik|klinik|rumah sakit|dokter|obat|farmasi|vitamin|lab\b|gigi|optik", "Kesehatan"),
    (r"bioskop|cinema|\bxxi\b|cgv|steam|spotify|netflix|konser|wisata|hotel|liburan|game", "Hiburan"),
    (r"sekolah|kuliah|buku|kursus|\bles\b|seminar|udemy|course|\bspp\b|\bukt\b", "Pendidikan"),
    (r"indomaret|alfamart|alfamidi|superindo|hypermart|transmart|carrefour|giant|minimarket|supermarket|grocer|pasar|shopee|tokopedia|lazada|blibli|belanja", "Belanja"),
    (r"resto|restoran|warung|warteg|makan|minum|kopi|coffee|cafe|kafe|bakso|sate|ayam|nasi|mie|martabak|\bkfc\b|\bmcd\b|mcdonald|burger|pizza|starbucks|chatime|\bjco\b|donat|roti|seafood|soto|geprek|food|kitchen|catering", "Makan & Minum"),
    (r"gaji|payroll|salary", "Gaji"),
    (r"bonus|thr|insentif", "Bonus"),
]


def _match_rule(text: str, categories: dict[str, Category]) -> Category | None:
    haystack = text.lower()
    for pattern, name in CATEGORY_RULES:
        if name in categories and re.search(pattern, haystack):
            return categories[name]
    return None


async def classify_category(
    db: Session,
    merchant_raw: str | None,
    text: str = "",
    use_llm: bool = True,
) -> tuple[int | None, str]:
    """Tentukan category_id dan sumbernya."""
    categories = {row.name: row for row in db.scalars(select(Category)).all()}

    # 1. Ingatan merchant (persis)
    merchant = find_exact(db, merchant_raw)
    if merchant and merchant.category_id:
        merchant.hits += 1
        return merchant.category_id, "merchant"

    # 2. Aturan keyword
    matched = _match_rule(f"{merchant_raw or ''} {text}", categories)
    if matched:
        return matched.id, "rule"

    # 3. Ingatan merchant (mirip)
    similar, _score = find_fuzzy(db, merchant_raw)
    if similar and similar.category_id:
        similar.hits += 1
        return similar.category_id, "fuzzy"

    # 4. LLM lokal - skip by default buat speed
    if use_llm and settings.llm_enabled and merchant_raw and len(merchant_raw.strip()) > 2:
        try:
            chosen = await llm.classify_merchant(merchant_raw, list(categories.keys()))
            if chosen and chosen in categories:
                return categories[chosen].id, "llm"
        except Exception:
            pass

    # 5. Tidak ada yang cocok
    fallback = categories.get("Lainnya")
    return (fallback.id if fallback else None), "none"
