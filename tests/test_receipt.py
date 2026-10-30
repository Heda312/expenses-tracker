"""Test parser struk dengan data sintetis.

Kalau nanti ada teks OCR asli, tambahkan sebagai fixture baru di sini.
"""

from datetime import date

from app.services.receipt import parse_receipt


def _line(text: str, top: int, height: int = 20) -> dict:
    return {"text": text, "top": top, "left": 10, "height": height, "score": 0.9}


def test_receipt_with_total_keyword():
    lines = [
        _line("INDOMARET", 10, 26),
        _line("JL SUDIRMAN NO 12", 40),
        _line("14/10/2026 19:42", 70),
        _line("ROTI 12.000", 120),
        _line("SUSU 35.500", 150),
        _line("TOTAL 47.500", 200, 28),
    ]

    data = parse_receipt(lines)

    assert data.amount == 47500
    assert data.merchant == "INDOMARET"
    assert data.date == date(2026, 10, 14)
    assert data.found_total_keyword is True
    assert data.confidence >= 0.85


def test_receipt_ignores_change_and_subtotal():
    lines = [
        _line("TOKO MAKMUR", 10),
        _line("SUB TOTAL 47.500", 100),
        _line("TOTAL 47.500", 130),
        _line("TUNAI 50.000", 160),
        _line("KEMBALIAN 2.500", 190),
    ]

    data = parse_receipt(lines)

    assert data.amount == 47500


def test_receipt_fallback_without_keyword():
    lines = [
        _line("WARUNG PAK BUDI", 10),
        _line("NASI GORENG 25.000", 100),
        _line("ES TEH 5.000", 130),
        _line("45.000", 200),
    ]

    data = parse_receipt(lines)

    assert data.amount == 45000
    assert data.found_total_keyword is False


def test_receipt_empty():
    data = parse_receipt([])

    assert data.amount is None
    assert data.merchant is None
    assert data.confidence == 0.0
