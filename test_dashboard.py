"""Test dashboard endpoint."""
import sys
sys.path.insert(0, "D:\\my_project\\expenses")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

try:
    r = client.get('/')
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print("Response (first 500 chars):")
        print(r.text[:500])
    else:
        print("OK - 200")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
