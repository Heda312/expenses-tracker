from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post("/login", data={"username": "admin", "password": "adminpassword123"}, follow_redirects=False)
r = client.get("/")
print(r.status_code)
print(r.text[:3000])
