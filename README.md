# Catat —Expense Tracker Sederhana

Pencatat pengeluaran dengan input via Telegram bot (foto struk + teks) dan web dashboard.

## Fitur

- Telegram bot: kirim struk/foto, OCR otomatis, konfirmasi via tombol inline
- Web app: dashboard gelap, filter, edit, hapus, export Excel
- Budget per kategori dengan progress bar
- Dompet multiple (tunai, bank, e-wallet)
- Kategori auto-detect: merchant alias → keyword → fuzzy → LLM → "Lainnya"
- Single-user login, session DB-backed, lockout 5 failed/15 menit
- SQLite + WAL (baca/tulis paralel bot + web)
- Data: uang INTEGER rupiah, waktu UTC (tampilAsia/Jakarta)

## Prasyarat

- Python 3.11+ (untuk dev)
- Docker & Docker Compose (untuk deploy)
- Token bot Telegram
- (Opsional) Akun Ollama lokal untuk kategori LLM

## Dev Setup (Windows/Linux)

1. Clone atau copy project ini ke folder lokal
2. Install dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

3. Copy `.env.example` ke `.env`, sesuaikan:

```bash
cp .env.example .env
# edit .env
```

4. Jalankan migrasi:

```bash
python -m alembic upgrade head
```

5. Buat user login:

```bash
python -m app.cli create-user --email anda@contoh.com
```

6. Jalankan server:

```bash
uvicorn app.main:app --reload
```

7. Buka `http://localhost:8000`

## Deploy dengan Docker

1. Copy project ke Linux VPS/homelab
2. Buat `.env` seperti di atas (set `TUNNEL_TOKEN` untuk Cloudflare)
3. Jalankan:

```bash
docker-compose build
docker-compose up -d
```

4. Setup tunnel (Cloudflare), akses via URL yang diberikan

## Telegram Bot

1. Buat bot via @BotFather, dapat token
2. Dapatkan `chat_id` Anda via @userinfobot
3. Set di `.env`:
   - `TELEGRAM_BOT_TOKEN=...`
   - `TELEGRAM_ALLOWED_CHAT_ID=<id-anda>`

Bot hanya merespons chat dari `TELEGRAM_ALLOWED_CHAT_ID`.

## OCR & LLM

- OCR pakai `rapidocr-onnxruntime` (PaddleOCR ONNX), jalan otomatis
- Kategori auto-detect: 5 layer
- LLM (Ollama) hanya dipakai kalau `LLM_ENABLED=true` dan gagal 4 layer pertama

## Struktur Project

```
.
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── seed.py
│   ├── cli.py
│   ├── main.py
│   ├── bot.py
│   ├── security.py
│   ├── schemas.py
│   ├── templating.py
│   ├── routers/        # auth, dashboard, transactions, accounts, budgets, export, settings
│   ├── services/       # money, dates, merchant, ocr, receipt, classify, ingest, ledger, xlsx
│   └── static/         # app.css, app.js
├── alembic/            # migration scripts
├── tests/              # pytest
├── data/               # database + uploads (gitignore)
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Troubleshooting

- Bot tidak merespons? Cek `TELEGRAM_ALLOWED_CHAT_ID`
- OCR gagal? Pastikan Python <3.13, coba foto lebih terang
- Uang tidak muncul? Pastikan `DATABASE_URL` benar, jalankan `alembic upgrade head`
- Dashboard blank? Cek `/login`, pastikan user sudah dibuat

## License

MIT
