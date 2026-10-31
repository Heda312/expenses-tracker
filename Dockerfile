FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Dependencies untuk OCR (PaddleOCR ONNX)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependencies dulu biar cache tetap jalan saat code berubah
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy aplikasi
COPY app/ ./app/
COPY alembic.ini ./
COPY alembic/ ./alembic/

VOLUME /app/data

EXPOSE 8000

# Alembic migrasi saat start
CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
