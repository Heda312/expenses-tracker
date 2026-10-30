"""Test untuk parser nominal. Jalankan: pytest"""

import pytest

from app.services.money import extract_amount, format_idr, parse_amount


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Rp 47.500", 47500),
        ("47500", 47500),
        ("50rb", 50000),
        ("50 rb", 50000),
        ("50k", 50000),
        ("1,5jt", 1500000),
        ("1.500.000", 1500000),
        ("1.500.000,00", 1500000),
        ("Rp 1.234.567", 1234567),
        ("-25.000", -25000),
        ("47.500", 47500),
        ("", None),
        ("abc", None),
        (None, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("makan siang 35rb", 35000),
        ("beli 2 kopi 35000", 35000),
        ("parkir 5rb pake gopay", 5000),
        ("gaji 8jt masuk bca", 8000000),
        ("bayar kos 1,5jt", 1500000),
        ("tidak ada nominal", None),
    ],
)
def test_extract_amount(text, expected):
    assert extract_amount(text) == expected


def test_format_idr():
    assert format_idr(47500) == "Rp 47.500"
    assert format_idr(0) == "Rp 0"
    assert format_idr(-2500) == "-Rp 2.500"
