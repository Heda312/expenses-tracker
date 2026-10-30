"""Test parser tanggal."""

from datetime import date

import pytest

from app.services.dates import format_dt, month_bounds, parse_date, shift_period


@pytest.mark.parametrize(
    "text,expected",
    [
        ("14/10/2026", date(2026, 10, 14)),
        ("14-10-26", date(2026, 10, 14)),
        ("14.10.2026", date(2026, 10, 14)),
        ("2026-10-14", date(2026, 10, 14)),
        ("14 Okt 2026", date(2026, 10, 14)),
        ("14 Oktober 2026", date(2026, 10, 14)),
        ("31/02/2026", None),
        ("tidak ada tanggal", None),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_parse_date_relative():
    base = date(2026, 10, 30)
    assert parse_date("kemarin", base=base) == date(2026, 10, 29)
    assert parse_date("tadi", base=base) == base


def test_shift_period():
    assert shift_period("2026-01", -1) == "2025-12"
    assert shift_period("2026-12", 1) == "2027-01"
    assert shift_period("2026-10", 0) == "2026-10"


def test_month_bounds_length():
    start, end = month_bounds("2026-10")
    assert end > start


def test_format_dt_uses_local_timezone():
    text = format_dt(None)
    assert text == "-"
