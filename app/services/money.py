"""Parsing dan format nominal rupiah.

Ini file paling penting di aplikasi. Semua uang yang masuk ke database
harus lewat sini, supaya tidak ada perbedaan tafsir "47.500" vs "47,500".
"""

import re

# Pengali untuk singkatan yang sering dipakai orang Indonesia.
SUFFIX_MULTIPLIER = {
    "rb": 1_000,
    "ribu": 1_000,
    "k": 1_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
    "m": 1_000_000_000,
}

_SUFFIX_RE = re.compile(r"(ribu|rb|juta|jt|k)$")
_NUMBER_RE = re.compile(r"-?\d[\d.,]*")


def _to_number(text: str) -> float:
    """Ubah string angka dengan pemisah ribuan/desimal ala Indonesia.

    Aturannya: pemisah yang muncul lebih dari sekali selalu pemisah ribuan,
    dan pemisah dengan tepat 3 digit di belakangnya juga dianggap ribuan.
    """
    s = text
    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):  # 1.500,50 -> desimal koma
            s = s.replace(".", "").replace(",", ".")
        else:  # 1,500.50 -> desimal titik
            s = s.replace(",", "")
    elif has_comma:
        parts = s.split(",")
        if len(parts) > 2 or len(parts[-1]) == 3:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif has_dot:
        parts = s.split(".")
        if len(parts) > 2 or len(parts[-1]) == 3:
            s = s.replace(".", "")

    return float(s)


def parse_amount(raw: str | int | float | None) -> int | None:
    """Ambil nominal dari teks bebas.

    Contoh yang didukung:
      "Rp 47.500"      -> 47500
      "47500"          -> 47500
      "50rb" / "50k"   -> 50000
      "1,5jt"          -> 1500000
      "1.500.000,00"   -> 1500000
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)

    text = str(raw).lower().strip()
    text = text.replace("rp", "").replace("idr", "")
    text = re.sub(r"\s+", "", text)
    if not text:
        return None

    multiplier = 1
    suffix = _SUFFIX_RE.search(text)
    if suffix:
        head = text[: suffix.start()]
        # Pastikan bagian depannya benar-benar angka, bukan kata biasa.
        if re.fullmatch(r"-?\d[\d.,]*", head):
            multiplier = SUFFIX_MULTIPLIER[suffix.group(1)]
            text = head

    match = _NUMBER_RE.search(text)
    if not match:
        return None

    try:
        value = _to_number(match.group(0)) * multiplier
    except ValueError:
        return None
    return int(round(value))


def extract_amount(text: str) -> int | None:
    """Cari nominal paling masuk akal di sebuah kalimat.

    Beda dengan parse_amount() yang mengambil angka pertama, fungsi ini
    mengutamakan angka yang punya satuan ("35rb") lalu angka terbesar,
    supaya "beli 2 kopi 35rb" tidak terbaca 2 rupiah.
    """
    if not text:
        return None

    with_suffix = re.search(r"\d[\d.,]*\s*(?:ribu|rb|juta|jt|k)\b", text, re.IGNORECASE)
    if with_suffix:
        return parse_amount(with_suffix.group(0))

    candidates = [parse_amount(token) for token in re.findall(r"-?\d[\d.,]*", text)]
    candidates = [c for c in candidates if c]
    if not candidates:
        return None

    big = [c for c in candidates if c >= 100]
    return max(big) if big else candidates[-1]


def format_idr(amount: int | None) -> str:
    """Format angka menjadi "Rp 47.500"."""
    value = int(amount or 0)
    sign = "-" if value < 0 else ""
    return f"{sign}Rp {abs(value):,.0f}".replace(",", ".")


def format_idr_compact(amount: int | None) -> str:
    """Format ringkas untuk sumbu chart: 1.250.000 -> "1,3 jt"."""
    value = int(amount or 0)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f} jt".replace(".", ",")
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f} rb"
    return str(value)
