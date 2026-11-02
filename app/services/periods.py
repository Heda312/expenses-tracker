"""Resolusi periode filter untuk dashboard dan daftar transaksi.

Satu sumber kebenaran untuk periode mingguan, bulanan, tahunan, rentang
manual, dan "semua waktu". Query string yang dipakai konsisten:

    period_type=week|month|year|custom|all
    period=<key>          # 2026-W45, 2026-11, 2026, all
    start=YYYY-MM-DD      # hanya untuk period_type=custom
    end=YYYY-MM-DD        # hanya untuk period_type=custom
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from app.services.dates import (
    MONTH_LABELS,
    TZ,
    current_period,
    month_bounds,
    period_label,
    shift_period,
    today_local,
    to_utc,
)

PERIOD_TABS = (
    ("week", "Minggu"),
    ("month", "Bulan"),
    ("year", "Tahun"),
    ("custom", "Rentang"),
    ("all", "Semua"),
)

WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


@dataclass(frozen=True)
class Period:
    """Periode yang sudah tervalidasi.

    ``start``/``end`` memakai UTC naive (end eksklusif) supaya langsung bisa
    dipakai di query SQLAlchemy. ``start_date``/``end_date`` adalah tanggal
    lokal inklusif untuk ditampilkan dan dipakai form.
    """

    type: str
    key: str
    start: datetime | None
    end: datetime | None
    start_date: date | None
    end_date: date | None
    label: str

    @property
    def is_all(self) -> bool:
        return self.type == "all"

    @property
    def has_range(self) -> bool:
        return self.start is not None and self.end is not None

    @property
    def month_key(self) -> str:
        """Bulan acuan untuk halaman budget/export yang masih bulanan."""
        if self.start_date is not None:
            return self.start_date.strftime("%Y-%m")
        return current_period()

    def params(self) -> dict[str, str]:
        """Query param minimal untuk mereproduksi periode ini."""
        if self.type == "all":
            return {"period_type": "all"}
        if self.type == "custom":
            return {
                "period_type": "custom",
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat(),
            }
        return {"period_type": self.type, "period": self.key}


def _date_label(value: date) -> str:
    return f"{value.day} {MONTH_LABELS[value.month - 1]} {value.year}"


def _range_label(start: date, end: date) -> str:
    if start == end:
        return _date_label(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {MONTH_LABELS[start.month - 1]} {start.year}"
    if start.year == end.year:
        return (
            f"{start.day} {MONTH_LABELS[start.month - 1]} – "
            f"{end.day} {MONTH_LABELS[end.month - 1]} {end.year}"
        )
    return f"{_date_label(start)} – {_date_label(end)}"


def _utc_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Tanggal lokal inklusif -> batas UTC naive (end eksklusif)."""
    start = to_utc(datetime.combine(start_date, time.min, tzinfo=TZ))
    end = to_utc(datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=TZ))
    return start, end


def _month_period(key: str) -> Period | None:
    match = MONTH_RE.match(key)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year, 12, 31)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    start, end = month_bounds(key)
    return Period("month", key, start, end, start_date, end_date, period_label(key))


def _week_key(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _week_period(key: str) -> Period | None:
    match = WEEK_RE.match(key)
    if not match:
        return None
    year, week = int(match.group(1)), int(match.group(2))
    try:
        start_date = date.fromisocalendar(year, week, 1)
    except ValueError:
        return None
    end_date = start_date + timedelta(days=6)
    start, end = _utc_bounds(start_date, end_date)
    return Period("week", _week_key(start_date), start, end, start_date, end_date, _range_label(start_date, end_date))


def _year_period(key: str) -> Period | None:
    if not (len(key) == 4 and key.isdigit()):
        return None
    year = int(key)
    if not (2000 <= year <= 2100):
        return None
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    start, end = _utc_bounds(start_date, end_date)
    return Period("year", key, start, end, start_date, end_date, f"Tahun {year}")


def _custom_period(start_raw: str | None, end_raw: str | None) -> Period:
    start_date = _parse_date(start_raw)
    end_date = _parse_date(end_raw)

    if start_date is None and end_date is None:
        return _default_custom_period()

    start_date = start_date or end_date
    end_date = end_date or start_date
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    start, end = _utc_bounds(start_date, end_date)
    key = f"{start_date.isoformat()}_{end_date.isoformat()}"
    return Period("custom", key, start, end, start_date, end_date, _range_label(start_date, end_date))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _all_period() -> Period:
    return Period("all", "all", None, None, None, None, "Semua waktu")


def _default_custom_period() -> Period:
    end_date = today_local()
    start_date = end_date - timedelta(days=29)
    start, end = _utc_bounds(start_date, end_date)
    key = f"{start_date.isoformat()}_{end_date.isoformat()}"
    return Period("custom", key, start, end, start_date, end_date, _range_label(start_date, end_date))


def resolve_period(
    period_type: str | None = None,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Period:
    """Ubah query param mentah menjadi :class:`Period` yang valid.

    Mendukung tautan lama ``?period=2026-11`` dan ``?period=all`` supaya
    bookmark atau link dari halaman lain tetap berjalan.
    """
    period_type = (period_type or "").strip().lower()
    period = (period or "").strip()

    if not period_type:
        if period == "all":
            return _all_period()
        if WEEK_RE.match(period):
            period_type = "week"
        elif len(period) == 4 and period.isdigit():
            period_type = "year"
        elif MONTH_RE.match(period):
            period_type = "month"
        elif start or end:
            period_type = "custom"
        else:
            period_type = "month"

    if period_type == "all":
        return _all_period()
    if period_type == "week":
        return _week_period(period) or _week_period(_week_key(today_local())) or _month_period(current_period())
    if period_type == "year":
        return _year_period(period) or _year_period(str(today_local().year)) or _month_period(current_period())
    if period_type == "custom":
        return _custom_period(start, end)
    return _month_period(period) or _month_period(current_period())


def shift_period_obj(period: Period, steps: int) -> Period | None:
    """Geser periode untuk navigasi prev/next."""
    if period.type == "month":
        return _month_period(shift_period(period.key, steps))
    if period.type == "week" and period.start_date is not None:
        return _week_period(_week_key(period.start_date + timedelta(weeks=steps)))
    if period.type == "year":
        return _year_period(str(int(period.key) + steps))
    return None


def previous_period(period: Period) -> Period | None:
    """Periode pembanding.

    Minggu/bulan/tahun memakai periode sebelumnya. Rentang manual memakai
    rentang dengan panjang yang sama tepat sebelum rentang berjalan.
    "Semua waktu" tidak punya pembanding.
    """
    if period.type == "custom" and period.start_date and period.end_date:
        length = (period.end_date - period.start_date).days + 1
        prev_end = period.start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
        start, end = _utc_bounds(prev_start, prev_end)
        key = f"{prev_start.isoformat()}_{prev_end.isoformat()}"
        return Period("custom", key, start, end, prev_start, prev_end, _range_label(prev_start, prev_end))
    if period.type == "all":
        return None
    return shift_period_obj(period, -1)


def period_for_type(period_type: str, current: Period | None = None) -> Period:
    """Periode default saat pengguna berpindah tab jenis periode."""
    if period_type == "all":
        return _all_period()
    if period_type == "week":
        return _week_period(_week_key(today_local())) or _month_period(current_period())
    if period_type == "year":
        return _year_period(str(today_local().year)) or _month_period(current_period())
    if period_type == "custom":
        if current and current.has_range and not current.is_all and current.start_date and current.end_date:
            start, end = _utc_bounds(current.start_date, current.end_date)
            key = f"{current.start_date.isoformat()}_{current.end_date.isoformat()}"
            return Period(
                "custom",
                key,
                start,
                end,
                current.start_date,
                current.end_date,
                _range_label(current.start_date, current.end_date),
            )
        return _default_custom_period()
    return _month_period(current_period())


def period_href(base_path: str, period: Period, extra: dict[str, str] | None = None) -> str:
    """Bangun URL dengan periode + filter tambahan (misalnya pencarian)."""
    params = period.params()
    if extra:
        params.update({key: value for key, value in extra.items() if value})
    query = urlencode(params)
    return f"{base_path}?{query}" if query else base_path


def build_period_context(
    period: Period,
    base_path: str,
    extra: dict[str, str] | None = None,
) -> dict:
    """Konteks siap pakai untuk partial ``_period_filter.html``."""
    tabs = []
    for period_type, label in PERIOD_TABS:
        target = period if period.type == period_type else period_for_type(period_type, period)
        tabs.append(
            {
                "type": period_type,
                "label": label,
                "active": period.type == period_type,
                "url": period_href(base_path, target, extra),
            }
        )

    prev_period = shift_period_obj(period, -1)
    next_period = shift_period_obj(period, 1)

    params = period.params()
    extra_params = {key: value for key, value in (extra or {}).items() if value}
    if extra_params:
        params.update(extra_params)

    return {
        "period": period,
        "period_tabs": tabs,
        "prev_url": period_href(base_path, prev_period, extra) if prev_period else None,
        "next_url": period_href(base_path, next_period, extra) if next_period else None,
        "period_query": urlencode(params),
        "period_params": params,
        "extra_params": extra_params,
        "custom_start": period.start_date.isoformat() if period.start_date else "",
        "custom_end": period.end_date.isoformat() if period.end_date else "",
        "filter_action": base_path,
    }
