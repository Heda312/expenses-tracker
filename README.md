# Catat

**Pencatat keuangan pribadi** dengan web dashboard, Telegram bot, dan REST API untuk agent eksternal.

Input transaksi lewat chat, foto struk (OCR), atau web. Saldo dompet dihitung otomatis dari transaksi. Semua data tersimpan lokal di SQLite.

**Versi:** 1.2.0 &nbsp;·&nbsp; **Lisensi:** MIT &nbsp;·&nbsp; **Python:** 3.11+

---

## Daftar Isi

- [Fitur](#fitur)
- [Tech Stack](#tech-stack)
- [Instalasi Windows](#instalasi-windows)
- [Instalasi Linux (Docker)](#instalasi-linux-docker)
- [Konfigurasi](#konfigurasi)
- [Menjalankan Aplikasi](#menjalankan-aplikasi)
- [Telegram Bot](#telegram-bot)
- [API untuk Hermes](#api-untuk-hermes)
- [Import & Export CSV](#import--export-csv)
- [Struktur Project](#struktur-project)
- [Testing](#testing)
- [Backup & Restore](#backup--restore)
- [Troubleshooting](#troubleshooting)
- [Changelog](#changelog)

---

## Fitur

### Web Dashboard

| Fitur | Keterangan |
|-------|------------|
| Dashboard | Ringkasan saldo, cashflow, budget, insight otomatis |
| Transaksi | CRUD lengkap, filter periode (minggu/bulan/tahun/rentang/semua) |
| Multi-dompet | Tunai, bank, e-wallet dengan **saldo dinamis** |
| Kategori | CRUD dengan warna otomatis |
| Budget | Progress per kategori dengan alert 70%/90%/100% |
| OCR Struk | Upload foto struk, nominal terisi otomatis |
| Import/Export | CSV transaksi (round-trip) dan Excel |

### Telegram Bot

| Fitur | Contoh |
|-------|--------|
| Input natural language | `makan 35rb`, `gaji 8jt` |
| OCR struk | Kirim foto → draft → konfirmasi |
| CRUD kategori | `tambah kategori Snack`, `hapus kategori Transport` |
| Budget tracking | `budget makanan 2jt`, `sisa budget` |
| Query info | `saldo`, `pengeluaran bulan ini`, `merchant terbanyak` |
| Import CSV | Kirim file `.csv` ke bot |

### REST API (untuk agent)

| Fitur | Keterangan |
|-------|------------|
| Auth Bearer token | `Authorization: Bearer <HERMES_API_TOKEN>` |
| CRUD transaksi/dompet/kategori | JSON, auto-create dompet & kategori |
| Import CSV | Multipart atau JSON string |
| Dokumentasi | `docs/API_HERMES.md` + Swagger di `/docs` |

### Keunggulan desain

- **Saldo dompet dinamis** — tidak pernah dipatok; selalu dihitung dari transaksi
  (`saldo_awal + masuk − keluar − transfer_keluar + transfer_masuk`).
- **Dompet & kategori otomatis** — terbentuk dari transaksi saat import, tanpa
  perlu setup manual.
- **Jenis dompet terbawa** — tunai/bank/e-wallet tersimpan di kolom
  `Jenis Dompet` dan ditebak dari nama jika kosong.
- **No LLM** — parsing deterministik, cepat, tanpa biaya API.

---

## Tech Stack

| Komponen | Teknologi |
|----------|-----------|
| Web | FastAPI + Jinja2 + Uvicorn |
| Database | SQLite + SQLAlchemy 2.x + Alembic |
| Bot | aiogram 3.x |
| OCR | RapidOCR (ONNX) + EasyOCR (fallback) |
| Parsing | rapidfuzz + regex |
| Keamanan | Argon2id + session cookie |
| Export | openpyxl (Excel), csv |

---

## Instalasi Windows

### Prasyarat

- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
  (centang **"Add python.exe to PATH"** saat instalasi)
- **Git** — [git-scm.com](https://git-scm.com/download/win)
- **Visual C++ Redistributable** — wajib untuk RapidOCR/ONNX
  ([unduh x64](https://aka.ms/vs/17/release/vc_redist.x64.exe))

### Langkah

```powershell
# 1. Clone repo
git clone https://github.com/Heda312/expenses-tracker.git
cd expenses-tracker

# 2. Buat virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# Jika muncul error execution policy:
# Set-ExecutionPolicy -Scope Process Bypass

# 3. Install dependency
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Siapkan konfigurasi
Copy-Item .env.example .env
notepad .env          # isi SECRET_KEY & token bot

# 5. Jalankan
python -m uvicorn app.main:app --reload
```

Buka **http://127.0.0.1:8000** → daftar akun → mulai catat.

### Menggunakan VSCode

1. **File → Open Folder** → pilih folder project
2. `Ctrl+Shift+P` → **Python: Select Interpreter** → pilih `.venv\Scripts\python.exe`
3. **Terminal → New Terminal**, lalu:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

### Catatan Windows

- OCR butuh **Visual C++ Redistributable**; tanpa itu RapidOCR gagal dimuat
  (aplikasi tetap jalan, OCR akan fallback ke EasyOCR).
- Kalau aktivasi venv diblokir, jalankan sekali:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- Port 8000 dipakai proses lain? Ganti: `--port 8080`

---

## Instalasi Linux (Docker)

Cara paling praktis untuk server/NAS/VPS. Docker menangani semua dependency
sistem OCR (libGL, libgomp, dll).

### Prasyarat

- **Docker Engine 24+** dan **Docker Compose v2**

```bash
# Debian/Ubuntu
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # lalu logout & login ulang
```

### Langkah

```bash
# 1. Clone repo
git clone https://github.com/Heda312/expenses-tracker.git
cd expenses-tracker

# 2. Siapkan folder data & konfigurasi
mkdir -p data/uploads
cp .env.example .env
nano .env                       # isi SECRET_KEY & token bot

# 3. Build & jalankan
docker compose up -d --build

# 4. Cek status
docker compose ps
docker compose logs -f app
```

Buka **http://IP-SERVER:8000**.

### Perintah harian

```bash
docker compose logs -f app      # lihat log
docker compose restart app      # restart
docker compose down             # hentikan
docker compose up -d --build    # update setelah git pull
```

### Cloudflare Tunnel (opsional)

Untuk akses dari luar tanpa buka port, isi `TUNNEL_TOKEN` di `.env` lalu:

```bash
docker compose --profile tunnel up -d
```

### Instalasi Linux tanpa Docker

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv git \
  libgomp1 libglib2.0-0 libgl1 libsm6 libxext6 libxrender1

python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
nano .env

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Systemd service (produksi)

`/etc/systemd/system/catat.service`:

```ini
[Unit]
Description=Catat Expense Tracker
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/expenses-tracker
Environment="PATH=/opt/expenses-tracker/.venv/bin"
ExecStart=/opt/expenses-tracker/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now catat
sudo systemctl status catat
```

---

## Konfigurasi

Salin `.env.example` menjadi `.env`:

```env
# Aplikasi
APP_NAME="Catat"
SECRET_KEY="ganti-dengan-string-acak-minimal-32-karakter"

# Database
DATABASE_URL="sqlite:///data/app.db"

# Sesi login
SESSION_DAYS=30
COOKIE_SECURE=false
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCK_MINUTES=15

# Telegram (opsional)
TELEGRAM_BOT_TOKEN=""
TELEGRAM_ALLOWED_CHAT_ID=""
# TELEGRAM_WEBHOOK_URL="https://domain.com/webhook/telegram"

# API untuk agent eksternal (opsional)
HERMES_API_TOKEN=""

# Migrasi otomatis saat startup
AUTO_MIGRATE=true

# Zona waktu
TIMEZONE="Asia/Jakarta"
```

### Tabel variabel

| Variabel | Wajib | Default | Keterangan |
|---|---|---|---|
| `APP_NAME` | – | `Catat` | Nama aplikasi di UI |
| `SECRET_KEY` | ✅ | – | Key sesi login (min. 32 karakter) |
| `DATABASE_URL` | – | `sqlite:///data/app.db` | Lokasi database SQLite |
| `SESSION_DAYS` | – | `30` | Masa berlaku sesi login |
| `COOKIE_SECURE` | – | `false` | Set `true` jika sudah HTTPS |
| `LOGIN_MAX_ATTEMPTS` | – | `5` | Batas percobaan login |
| `LOGIN_LOCK_MINUTES` | – | `15` | Durasi lockout |
| `TELEGRAM_BOT_TOKEN` | – | – | Token dari @BotFather |
| `TELEGRAM_ALLOWED_CHAT_ID` | – | – | Chat ID yang diizinkan |
| `TELEGRAM_WEBHOOK_URL` | – | – | Kosong = mode polling |
| `HERMES_API_TOKEN` | – | – | Token Bearer untuk `/api/v1` |
| `AUTO_MIGRATE` | – | `true` | Jalankan Alembic saat startup |
| `TIMEZONE` | – | `Asia/Jakarta` | Zona waktu tampilan |

Generate `SECRET_KEY` dan `HERMES_API_TOKEN`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Menjalankan Aplikasi

```bash
# Development (auto-reload)
python -m uvicorn app.main:app --reload

# Produksi
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

| URL | Keterangan |
|---|---|
| `http://127.0.0.1:8000` | Dashboard |
| `http://127.0.0.1:8000/docs` | Swagger API |
| `http://127.0.0.1:8000/health` | Health check |

> **Catatan:** gunakan `--workers 1`. Bot Telegram berjalan di dalam proses
> aplikasi; lebih dari satu worker akan membuat bot menerima update ganda.

Saat pertama dibuka, aplikasi mengarahkan ke halaman **Daftar** untuk membuat
akun admin.

---

## Telegram Bot

1. Buat bot di [@BotFather](https://t.me/BotFather) → salin token
2. Dapatkan chat ID Anda (kirim pesan ke [@userinfobot](https://t.me/userinfobot))
3. Isi `.env`:

```env
TELEGRAM_BOT_TOKEN="123456:ABC..."
TELEGRAM_ALLOWED_CHAT_ID="8617947659"
```

4. Restart aplikasi. Bot otomatis jalan dalam mode polling.

### Contoh perintah

```
makan 35rb
gaji 8jt
transfer 500rb bca ke gopay

budget makanan 2jt
sisa budget
saldo
pengeluaran bulan ini
merchant terbanyak

tambah kategori Snack
hapus kategori Transport
```

---

## API untuk Hermes

Dokumentasi lengkap: **[`docs/API_HERMES.md`](docs/API_HERMES.md)**

```env
HERMES_API_TOKEN="token-acak-panjang"
```

```bash
# Catat pengeluaran (dompet & kategori otomatis dibuat)
curl -X POST http://127.0.0.1:8000/api/v1/transactions \
  -H "Authorization: Bearer $HERMES_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"expense","amount":"35rb","account":"BCA","category":"Makanan","merchant":"Indomaret"}'

# Cek saldo
curl http://127.0.0.1:8000/api/v1/summary \
  -H "Authorization: Bearer $HERMES_API_TOKEN"
```

Endpoint utama: `/api/v1/transactions`, `/api/v1/accounts`, `/api/v1/categories`,
`/api/v1/summary`, `/api/v1/budgets`, `/api/v1/import/csv/text`.

---

## Import & Export CSV

### Export

Halaman **Transaksi** → tombol **Export**:

| Format | Isi |
|---|---|
| `catat-transaksi-YYYY-MM.csv` | Transaksi saja — bisa di-import ulang |
| `catat-YYYY-MM.xlsx` | Excel laporan (transaksi + ringkasan + budget) |

Export **hanya berisi transaksi**. Dompet dan kategori tidak diekspor terpisah —
keduanya terbentuk otomatis saat import.

### Import

Halaman **Settings** → **Import CSV**, atau via bot/API.

```csv
Tanggal,Waktu,Jenis,Nominal,Kategori,Merchant,Dompet,Jenis Dompet,Dompet Tujuan,Catatan
2026-11-07,14:30:00,Pengeluaran,15000,Makanan,Indomaret,BCA,bank,,
2026-11-07,19:05:00,Pemasukan,8000000,Gaji,Kantor,BCA,bank,,
2026-11-08,08:00:00,Transfer,500000,,,BCA,bank,GoPay,
```

| Kolom | Wajib | Keterangan |
|---|---|---|
| `Tanggal` | – | `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY` |
| `Waktu` | – | `HH:MM` / `HH:MM:SS` — digabung dengan Tanggal |
| `Jenis` | – | Pengeluaran / Pemasukan / Transfer |
| `Nominal` | ✅ | `15000`, `15.000`, `15rb` |
| `Kategori` | – | Auto-create |
| `Merchant` | – | Nama toko |
| `Dompet` | – | Auto-create |
| `Jenis Dompet` | – | `bank`, `ewallet`, `cash` (kosong = ditebak dari nama) |
| `Dompet Tujuan` | – | Wajib untuk baris Transfer |

Setelah import, saldo semua dompet dihitung ulang otomatis.

---

## Struktur Project

```
expenses/
├── app/
│   ├── main.py              # Entry point FastAPI
│   ├── bot.py               # Telegram bot
│   ├── models.py            # Model SQLAlchemy
│   ├── schemas.py           # Validasi Pydantic
│   ├── config.py            # Konfigurasi dari .env
│   ├── db.py                # Engine & session
│   ├── security.py          # Auth, Argon2, session
│   ├── schema_patch.py      # Penambal kolom skema
│   ├── seed.py              # Data awal
│   ├── webhook.py           # Webhook Telegram
│   ├── routers/
│   │   ├── api.py           # REST API /api/v1 (Hermes)
│   │   ├── auth.py          # Login/register/logout
│   │   ├── dashboard.py     # Dashboard
│   │   ├── transactions.py  # CRUD transaksi
│   │   ├── accounts.py      # CRUD dompet
│   │   ├── categories.py    # CRUD kategori + import CSV
│   │   ├── budgets.py       # Budget
│   │   ├── export.py        # Export Excel/CSV
│   │   ├── ocr.py           # Endpoint OCR
│   │   └── settings_page.py # Halaman settings
│   ├── services/
│   │   ├── wallet.py        # Saldo dompet dinamis + auto-create
│   │   ├── importer.py      # Import CSV (round-trip)
│   │   ├── export_formats.py# Format CSV
│   │   ├── ledger.py        # Agregasi laporan
│   │   ├── dashboard.py     # Data dashboard
│   │   ├── analytics.py     # Insight
│   │   ├── periods.py       # Resolusi periode
│   │   ├── dates.py         # Util tanggal & timezone
│   │   ├── money.py         # Parsing nominal rupiah
│   │   ├── ocr.py           # OCR engine wrapper
│   │   ├── receipt.py       # Parser struk
│   │   ├── classify.py      # Deteksi kategori
│   │   ├── merchant.py      # Ingatan merchant
│   │   ├── cleanup.py       # Hapus dompet/kategori (FK-safe)
│   │   ├── budget_alerts.py # Alert budget
│   │   ├── ingest.py        # Draft transaksi
│   │   └── xlsx.py          # Export Excel
│   ├── templates/           # Template Jinja2
│   └── static/              # CSS & JS
├── alembic/
│   └── versions/            # Migrasi database
├── docs/
│   └── API_HERMES.md        # Dokumentasi API
├── scripts/                 # Skrip bantu & smoke test
├── tests/                   # Unit & integration test
├── data/                    # SQLite + upload (gitignored)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── requirements-dev.txt
```

---

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Tes memakai database sementara (`tests/conftest.py`) — **tidak menyentuh**
`data/app.db`.

```bash
# Smoke test halaman web
$env:PYTHONPATH="."; python scripts/smoke_pages.py     # Windows
PYTHONPATH=. python scripts/smoke_pages.py             # Linux
```

---

## Backup & Restore

### Backup

```bash
# SQLite: salin file db (hentikan aplikasi dulu untuk konsistensi)
docker compose stop app
cp data/app.db backup/app-$(date +%F).db
docker compose start app
```

Atau lewat aplikasi: **Transaksi → Export → CSV transaksi** (bisa di-import ulang).

### Restore

```bash
docker compose stop app
cp backup/app-2026-11-07.db data/app.db
docker compose start app
```

---

## Troubleshooting

### Bot tidak merespons

- Pastikan `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_ALLOWED_CHAT_ID` benar
- Cek log: `docker compose logs -f app` atau terminal
- Satu bot hanya boleh satu instance (jangan jalankan lokal + server bersamaan)

### OCR gagal

- **Windows:** install [VC++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- **Docker/Linux:** pastikan `libgomp1 libgl1 libglib2.0-0` terpasang
- Aplikasi otomatis fallback ke EasyOCR kalau RapidOCR gagal

### Import CSV gagal

- Kolom **Nominal** wajib ada
- Baris transfer butuh **Dompet Tujuan** yang berbeda dari **Dompet**
- Format tanggal yang didukung: `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`

### Saldo dompet tidak sesuai

Buka **Dompet → Sinkronkan saldo**, atau panggil
`POST /api/v1/accounts/sync`. Saldo selalu dihitung ulang dari transaksi
`confirmed` yang belum dihapus.

### Tidak bisa hapus dompet

Dompet yang masih punya transaksi **aktif** dilindungi. Hapus/pindahkan
transaksinya dulu, atau gunakan panel hapus di halaman Dompet untuk menghapus
sekaligus (`?force=true` via API).

### Port 8000 sudah dipakai

```bash
python -m uvicorn app.main:app --port 8080
```

---

## Changelog

Lihat **[CHANGELOG.md](CHANGELOG.md)** dan **[RELEASE_NOTES_v1.2.0.md](RELEASE_NOTES_v1.2.0.md)**.

---

## Lisensi

MIT — lihat [LICENSE](LICENSE).

## Kredit

Dibangun dengan FastAPI, aiogram, SQLAlchemy, RapidOCR, dan EasyOCR.
