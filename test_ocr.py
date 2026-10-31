"""Test OCR with a sample receipt image."""
import sys
sys.path.insert(0, "D:\\opencode")

from app.services.ocr import read_lines, OcrError

# Test dengan gambar sample
test_image_path = "D:\\opencode\\tests\\data\\sample_receipt.jpg"

try:
    with open(test_image_path, "rb") as f:
        image_bytes = f.read()
    
    print(f"Reading image: {len(image_bytes)} bytes")
    lines = read_lines(image_bytes)
    print(f"Found {len(lines)} lines:")
    for line in lines[:10]:
        print(f"  [{line['top']:3.0f}] {line['text']}")
except FileNotFoundError:
    print(f"Test image not found: {test_image_path}")
    print("Create sample receipt image first, or test with real uploaded file")
except OcrError as e:
    print(f"OCR error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
