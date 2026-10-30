"""Parser struk: dari baris teks OCR menjadi data terstruktur.

Semua keputusan di sini deterministik (tanpa LLM), karena nominal uang
tidak boleh ditebak. Kalau ragu, confidence turun dan pengguna ditanya.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.services.dates import parse_date
from app.services.money import parse_amount

# Baris yang biasanya berisi total akhir.
TOTAL_PATTERN = re.compile(
    r"(grand\s*total|total\s*bayar|total\s*pembayaran|jumlah\s*bayar|jumlah\s*tagihan|tagihan|yang\s*harus\s*dibayar|amount|total\s*yang\s*dibayar|total)",
    re.IGNORECASE,
)

# Baris yang mirip total tapi bukan total akhir.
EXCLUDE_PATTERN = re.compile(
    r"(sub\s*total|subtotal|kembali|kembalian|tunai|cash|diskon|potongan|hemat|ppn|pajak|tax|service|biaya\s*admin|admin|fee|refund|saldo|saldo\s*akhir|detail)",
    re.IGNORECASE,
)

MERCHANT_NOISE = re.compile(
    r"(struk|nota|invoice|terima\s*kasih|kasir|npwp|telp|tlp|alamat|no\.\s*|id\s*transaksi|waktu|tanggal)",
    re.IGNORECASE,
)


@dataclass
class ReceiptData:
    amount: Optional[int] = None
    date: Optional[date] = None
    merchant: Optional[str] = None
    items: list[tuple[str, int]] = field(default_factory=list)
    confidence: float = 0.0
    raw_text: str = ""
    found_total_keyword: bool = False


def _last_amount(text: str) -> int | None:
    text = text.lower().replace("idr", "rp")
    tokens = re.findall(r"(?:rp\.?\s*)?\d[\d.,]+", text)
    for token in reversed(tokens):
        clean = token.replace("rp", "").replace(" ", "")
        num_clean = clean.replace(".", "").replace(",", "")
        if not num_clean.isdigit():
            continue
        if len(num_clean) < 3 or len(num_clean) == 3:
            continue
        value = parse_amount(clean)
        if value and value >= 1000:
            return value
    return None


def _find_total(lines: list[dict]) -> tuple[int | None, bool]:
    if not lines:
        return None, False

    # 1) Keyword
    for index, line in enumerate(lines):
        text = line["text"]
        if not TOTAL_PATTERN.search(text):
            continue
        if EXCLUDE_PATTERN.search(text):
            continue
        amount = _last_amount(text)
        if amount is None:
            for offset in (1, 2, 3):
                if index + offset < len(lines):
                    amount = _last_amount(lines[index + offset]["text"])
                    if amount:
                        break
        if amount:
            return amount, True

    # 2) Baris ada "Rp" + nominal gede, ambil yang paling bawah
    rp_list = []
    for line in lines:
        text = line["text"]
        if EXCLUDE_PATTERN.search(text):
            continue
        if "rp" in text.lower():
            amount = _last_amount(text)
            if amount and amount >= 2000:
                rp_list.append((line["top"], amount))
    if rp_list:
        rp_list.sort(key=lambda x: x[0])
        return rp_list[-1][1], False

    # 3) Nominal terbesar di 25% bawah
    max_top = max(line["top"] for line in lines)
    threshold = max_top * 0.75
    best = None
    best_top = -1
    for line in lines:
        if line["top"] < threshold:
            continue
        if EXCLUDE_PATTERN.search(line["text"]):
            continue
        amount = _last_amount(line["text"])
        if amount and amount >= 2000:
            if best is None or amount > best or (amount == best and line["top"] > best_top):
                best = amount
                best_top = line["top"]
    return best, False


def _find_merchant(lines: list[dict]) -> str | None:
    for line in lines[:8]:
        text = line["text"].strip()
        if not text:
            continue
        tl = text.lower()
        if re.search(r"\d{4,}", tl):
            continue
        if MERCHANT_NOISE.search(tl):
            continue
        if "rp" in tl:
            continue
        letters = sum(c.isalpha() for c in text)
        if letters >= 4 and len(text) <= 40:
            return text
    if lines:
        return lines[0]["text"].strip()
    return None


def parse_receipt(lines: list[dict]) -> ReceiptData:
    data = ReceiptData()
    if not lines:
        return data

    data.raw_text = "\n".join(line["text"] for line in lines)
    data.amount, data.found_total_keyword = _find_total(lines)
    data.merchant = _find_merchant(lines)
    data.date = parse_date(data.raw_text)

    conf = 0.0
    if data.amount:
        conf += 0.6
    if data.found_total_keyword:
        conf += 0.2
    if data.date:
        conf += 0.1
    if data.merchant:
        conf += 0.1
    data.confidence = round(min(conf, 1.0), 2)
    return data
