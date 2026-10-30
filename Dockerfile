FROM python:3.12-slim-bookworm

# Dependencies untuk OCR (PaddleOCR ONNX)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependencies dulu biar cache tetap jalan saat code berubah
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy aplikasi
COPY app/ ./app/
COPY alembic.ini ./

# Data volume (database & uploads)
VOLUME /app/data

# Alembic migrasi saat start
CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
