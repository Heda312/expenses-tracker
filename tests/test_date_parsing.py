"""Test date parsing for bot transactions."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date
from app.services.dates import parse_date, to_local_datetime

def test_date_parsing():
    base = date(2026, 10, 31)
    
    # Test relative dates
    assert parse_date("kemarin makan 20rb", base) == date(2026, 10, 30)
    assert parse_date("hari ini parkir 5rb", base) == date(2026, 10, 31)
    
    # Test numeric formats
    assert parse_date("30/10/2026", base) == date(2026, 10, 30)
    assert parse_date("tanggal 29-10-26", base) == date(2026, 10, 29)
    
    # Test ISO format
    assert parse_date("2026-10-28", base) == date(2026, 10, 28)
    
    # Test month names
    assert parse_date("25 oktober 2026", base) == date(2026, 10, 25)
    assert parse_date("25 okt 2026", base) == date(2026, 10, 25)
    
    print("Date parsing tests passed")
    
    # Test datetime conversion
    parsed = parse_date("kemarin", base)
    dt = to_local_datetime(parsed)
    print(f"kemarin -> {parsed} -> {dt}")
    assert dt.date() == date(2026, 10, 30)  # Should be yesterday
    
    print("All date tests passed")


if __name__ == "__main__":
    test_date_parsing()
