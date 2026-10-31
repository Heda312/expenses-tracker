"""Test OCR endpoint via HTTP."""
import requests

# Test dengan gambar yang sudah ada
files = {"file": ("test.jpg", open("D:\\opencode\\data\\uploads\\1da083cb227a459b9d0f9eb57b4ed1b0.jpg", "rb"), "image/jpeg")}

# Jika ada auth token, tambahkan header
# headers = {"Authorization": "Bearer <token>"}

try:
    resp = requests.post("http://127.0.0.1:8000/ocr", files=files)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
