"""Bantuan tanggal dan zona waktu.

Database selalu menyimpan UTC (naive). Tampilan dan input pengguna
selalu memakai zona waktu dari .env (default Asia/Jakarta).
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

TZ = ZoneInfo(settings.timezone)

MONTH_NAMES = {
    "jan": 1, "januari": 1,
    "feb": 2, "februari": 2, "peb": 2,
    "mar": 3, "maret": 3,
    "apr": 4, "april": 4,
    "mei": 5, "may": 5,
    "jun": 6, "juni": 6,
    "jul": 7, "juli": 7,
    "agu": 8, "agt": 8, "ags": 8, "aug": 8, "agustus": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10,
    "nov": 11, "november": 11,
    "des": 12, "desember": 12, "dec": 12,
}

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

DATE_FORMAT = "%d %b %Y"


def now_local() -> datetime:
    return datetime.now(TZ)


def today_local() -> date:
    return now_local().date()


def to_local(dt_utc: datetime) -> datetime:
    """UTC naive dari database -> datetime lokal (dengan tzinfo)."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(TZ)


def to_utc(local_dt: datetime) -> datetime:
    """Datetime lokal -> UTC naive untuk disimpan."""
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=TZ)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def now_utc() -> datetime:
    return to_utc(now_local())


def format_dt(dt_utc: datetime | None) -> str:
    if dt_utc is None:
        return "-"
    local = to_local(dt_utc)
    return f"{local.day} {MONTH_LABELS[local.month - 1]} {local.year} {local:%H:%M}"


def format_date(dt_utc: datetime | None) -> str:
    if dt_utc is None:
        return "-"
    local = to_local(dt_utc)
    return f"{local.day} {MONTH_LABELS[local.month - 1]} {local.year}"


def current_period() -> str:
    """Periode bulan berjalan, format YYYY-MM."""
    return today_local().strftime("%Y-%m")


def valid_period(value: str | None) -> str:
    """Pastikan periode berformat YYYY-MM, kalau tidak pakai bulan ini."""
    if value and len(value) == 7 and value[4] == "-":
        try:
            year, month = int(value[:4]), int(value[5:])
            if 2000 <= year <= 2100 and 1 <= month <= 12:
                return value
        except ValueError:
            pass
    return current_period()


def month_bounds(period: str) -> tuple[datetime, datetime]:
    """Batas awal dan akhir bulan dalam UTC naive."""
    year, month = int(period[:4]), int(period[5:])
    start_local = datetime(year, month, 1, tzinfo=TZ)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=TZ)
    else:
        end_local = datetime(year, month + 1, 1, tzinfo=TZ)
    return to_utc(start_local), to_utc(end_local)


def shift_period(period: str, months: int) -> str:
    """Geser periode beberapa bulan, contoh shift_period("2026-01", -1) -> "2025-12"."""
    year, month = int(period[:4]), int(period[5:])
    total = (year * 12 + (month - 1)) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def period_label(period: str) -> str:
    year, month = int(period[:4]), int(period[5:])
    return f"{MONTH_LABELS[month - 1]} {year}"


def parse_date(raw: str | None, base: date | None = None) -> date | None:
    """Cari tanggal di dalam teks.

    Mendukung: 14/10/2026, 14-10-26, 14 Okt 2026, 2026-10-14,
    serta kata "tadi" dan "kemarin".
    """
    if not raw:
        return None
    text = raw.lower()
    base = base or today_local()

    if "kemarin" in text:
        return base - timedelta(days=1)
    if "tadi" in text or "hari ini" in text:
        return base

    # ISO: 2026-10-14, termasuk timestamp ISO.
    import re

    iso = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", text)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    # Angka dengan pemisah: 14/10/2026, 14-10-26, 14.10.2026
    numeric = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", text)
    if numeric:
        day, month, year = (int(g) for g in numeric.groups())
        if year < 100:
            year += 2000
        result = _safe_date(year, month, day)
        if result:
            return result

    # Nama bulan: 14 Okt 2026 / 14 Oktober 2026
    named = re.search(r"\b(\d{1,2})\s+([a-z]+)\s+(\d{2,4})\b", text)
    if named:
        month = MONTH_NAMES.get(named.group(2))
        year = int(named.group(3))
        if year < 100:
            year += 2000
        if month:
            return _safe_date(year, month, int(named.group(1)))

    return None


def parse_time(raw: str | None) -> time | None:
    """Normalisasi berbagai format jam OCR menjadi ``datetime.time``.

    Mendukung 18:20, 18:20:15, 18.20, 182015, 1820,
    06:20 PM, 06.20.15pm, serta label seperti ``Time 18:20``.
    """
    if not raw:
        return None
    import re
    text = raw.lower().strip()
    # Separator titik/koma sering terbaca dari receipt sebagai jam.
    match = re.search(
        r"(?<!\d)(\d{1,2})\s*[:.]\s*(\d{2})"
        r"(?:\s*[:.]\s*(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?!\d)",
        text,
        re.I,
    )
    if not match:
        # Compact time: 1820 atau 182015. Hindari angka tanggal/nominal.
        match = re.search(r"(?<!\d)(\d{4}|\d{6})\s*(a\.?m\.?|p\.?m\.?)?(?!\d)", text, re.I)
        if not match:
            return None
        digits = match.group(1)
        hour = int(digits[:2])
        minute = int(digits[2:4])
        second = int(digits[4:6]) if len(digits) == 6 else 0
        suffix = match.group(2)
    else:
        hour, minute = int(match.group(1)), int(match.group(2))
        second = int(match.group(3) or 0)
        suffix = match.group(4)
    suffix = suffix.replace(".", "") if suffix else None
    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour, minute)
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def to_local_datetime(day: date, at: time | None = None) -> datetime:
    """Gabungkan tanggal + jam lokal menjadi datetime UTC naive."""
    local = datetime.combine(day, at or now_local().time().replace(microsecond=0), tzinfo=TZ)
    return to_utc(local)
