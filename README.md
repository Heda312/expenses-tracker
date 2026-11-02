# Catat

Expense Tracker Sederhana dengan Telegram Bot & Web Dashboard

---

## 📋 Konten

- [Tentang](#-tentang)
- [Fitur](#-fitur)
- [Quick Start](#-quick-start)
- [Telegram Bot](#-telegram-bot)
- [Web Dashboard](#-web-dashboard)
- [Installasi Docker](#-installasi-docker)
- [Konfigurasi](#-konfigurasi)
- [Struktur Project](#-struktur-project)
- [Tech Stack](#-tech-stack)
- [Backup & Restore](#-backup--restore)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Tentang

Catat adalah aplikasi tracking keuangan pribadi yang fokus pada kemudahan penggunaan.

- **Input cepat** via Telegram bot dengan natural language
- **Visualisasi jelas** via web dashboard
- **Self-contained** menggunakan SQLite
- **No LLM** — OCR + parsing sederhana untuk kecepatan maksimal

Versi 1.1.0 (current) — Grid layout UI, response format improved, CRUD transaksi via bot.

---

## ✨ Fitur

### Telegram Bot

| Fitur | Keterangan |
|-------|------------|
| 📸 OCR Struk | Upload foto, ekstrak nominal otomatis |
| 💬 Natural Language | Input transaksi: `makan 35rb`, `gaji 8jt` |
| 📁 CRUD Kategori | Tambah, ubah, hapus kategori via chat |
| 💼 Budget Tracking | Set budget per kategori dengan alert |
| 📊 Query Info | Tanya saldo, budget, transaksi |
| 📥 Import CSV | Bulk import via bot |

### Web Dashboard

| Fitur | Keterangan |
|-------|------------|
| 📈 Dashboard | Ringkasan saldo, cashflow, budget |
| 💰 Transaksi CRUD | Tambah, edit, delete transaksi |
| 📁 Kategori Custom | Kelola kategori tanpa default |
| 👛 Multi-Wallet | Cash, bank, e-wallet |
| 📥 Import/Export | CSV & Excel import/export |
| 🔍 Filter Periode | Bulan ini, bulan lalu, custom range |
| 🎨 Dark Mode | Theme gelap by default |

---

## 🚀 Quick Start

### Prasyarat

- Python 3.12+
- Docker & Docker Compose (rekomendasi)
- Token bot Telegram dari @BotFather

### Installasi Cepat (Docker)

```bash
git clone https://github.com/Heda312/expenses-tracker.git
cd expenses-tracker

cp .env.example .env
mkdir -p data/uploads

docker compose build
docker compose up -d
```

Akses: http://localhost:8000

---

## 📱 Telegram Bot

### Setup Bot

1. Buat bot via `@BotFather` → dapatkan token
2. Dapatkan `chat_id` via `@userinfobot`
3. Tambahkan ke `.env`:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ALLOWED_CHAT_ID=your_chat_id_here
```

### Perintah & Input

#### Input Transaksi (Natural Language)

```
makan siang 35rb warteg
parkir 5rb pake gopay
gaji 8jt masuk bca
bonus 500k pake bca
```

Format: `[merchant/keterangan] [nominal] [dompet]`

#### CRUD Kategori

```
tambah kategori Olahraga
tambah kategori Bonus pemasukan
hapus kategori Lain-lain
ubah kategori Makan jadi Makanan
/kategori
```

#### Budget

```
budget makanan 2jt
budget transport 500rb
budget bonus 1jt pemasukan
/budget
```

#### Query Info

```
berapa sisa saldo
berapa kategori
kategori apa saja
berapa transaksi bulan ini
budget apa saja
pengeluaran per kategori
merchant terbanyak
```

#### Laporan

```
/saldo          # Saldo semua akun
/ringkasan      # Kondisi keuangan bulan ini
/pengeluaran    # Total expense
/pemasukan      # Total income
/transaksi      # Transaksi terakhir
```

---

## 🖥️ Web Dashboard

### Halaman Utama

- **Dashboard**: Saldo total, cashflow, budget progress
- **Filter**: Pilih periode (bulan ini, lalu, custom)
- **Quick Add**: Tombol cepat tambah transaksi

### Manajemen Transaksi

- Tambah edit delete transaksi
- Pilih kategori, dompet
- Upload foto struk (OCR otomatis)
- Import CSV massal

### Manajemen Kategori

- Tambah kategori custom
- Set jenis (expense/income)
- Set warna otomatis
- Validasi penggunaan di transaksi

### Manajemen Akun

- Tambah akun (cash, bank, e-wallet)
- Set saldo awal
- Archive akun jika tidak aktif

### Budget Tracking

- Set budget per kategori
- Progress bar real-time
- Alert 70%, 90%, 100%

---

## 🐳 Installasi Docker

### 1. Setup Environment

```bash
cd expenses-tracker
cp .env.example .env
mkdir -p data/uploads
chmod 700 data
```

Edit `.env`:

```
APP_NAME="Catat"
SECRET_KEY="random-string-minimal-32-karakter"
DATABASE_URL="sqlite:///data/app.db"
UPLOAD_DIR="data/uploads"

TELEGRAM_BOT_TOKEN="your_token"
TELEGRAM_ALLOWED_CHAT_ID="your_chat_id"

TIMEZONE="Asia/Jakarta"
```

### 2. Build & Run

```bash
docker compose build
docker compose up -d
```

### 3. Cek Status

```bash
docker compose ps
docker compose logs -f app
```

### 4. Akses Aplikasi

- Web: http://localhost:8000
- Bot: @your_bot (hanya chat_id terdaftar)

---

## ⚙️ Konfigurasi

### File .env

| Variabel | Keterangan | Default |
|----------|------------|---------|
| `APP_NAME` | Nama aplikasi | "Catat" |
| `SECRET_KEY` | Key untuk session | *wajib diisi* |
| `DATABASE_URL` | URL SQLite | `sqlite:///data/app.db` |
| `UPLOAD_DIR` | Folder upload | `data/uploads` |
| `TELEGRAM_BOT_TOKEN` | Token bot | *wajib untuk bot* |
| `TELEGRAM_ALLOWED_CHAT_ID` | Chat ID allowed | *wajib untuk bot* |
| `TIMEZONE` | Zona waktu | "Asia/Jakarta" |

### Build Custom

```bash
# Tanpa tunnel
docker compose up -d

# Dengan cloudflared tunnel (set TUNNEL_TOKEN)
docker compose --profile tunnel up -d
```

---

## 📁 Struktur Project

```
expenses/
├── app/
│   ├── main.py           # FastAPI entry point
│   ├── bot.py            # Telegram bot logic
│   ├── models.py         # SQLAlchemy models
│   ├── config.py         # Configuration
│   ├── db.py             # Database session
│   ├── security.py       # Auth & password hashing
│   ├── seed.py           # Initial data
│   ├── cli.py            # CLI commands
│   ├── routers/
│   │   ├── auth.py       # Login/logout
│   │   ├── dashboard.py  # Dashboard page
│   │   ├── transactions.py
│   │   ├── accounts.py
│   │   ├── categories.py
│   │   ├── budgets.py
│   │   ├── export.py
│   │   ├── ocr.py
│   │   └── settings_page.py
│   ├── services/
│   │   ├── money.py      # Parsing nominals
│   │   ├── dates.py      # Date utilities
│   │   ├── ocr.py        # OCR engines
│   │   ├── classify.py   # Category detection
│   │   ├── ledger.py     # Balance calc
│   │   └── budget_alerts.py
│   ├── templates/        # Jinja2 templates
│   └── static/           # CSS & JS
├── alembic/
│   ├── env.py
│   └── versions/         # Migrations
├── data/                 # SQLite + uploads (gitignore)
├── tests/                # Unit tests
├── scripts/              # Helper scripts
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, FastAPI |
| Database | SQLite + SQLAlchemy + Alembic |
| Frontend | Jinja2, vanilla JS, modern CSS |
| Bot | aiogram 3.x |
| OCR | RapidOCR (fallback EasyOCR) |
| Security | Argon2 |
| Export | openpyxl (Excel) |
| Container | Docker + Docker Compose |

---

## 💾 Backup & Restore

### Backup

```bash
docker compose stop app
tar -czf catat-backup-$(date +%Y%m%d).tar.gz data/
docker compose start app
```

### Restore

```bash
docker compose stop app
tar -xzf catat-backup-*.tar.gz
docker compose start app
docker compose run --rm app python -m alembic upgrade head
docker compose up -d
```

### Manual Backup

Copy folder `data/` ke lokasi aman.

---

## 🔧 Troubleshooting

### Bot tidak merespons

```bash
# Cek logs
docker compose logs bot

# Pastikan config benar
grep -E "TELEGRAM" .env
```

### OCR gagal

- Pastikan Python < 3.13
- Foto harus jelas dan terang
- Coba rotate foto jika hasil buruk

### Import CSV gagal

- Format header: `tanggal,nominal,kategori,merchant,dompet`
- Encoding: UTF-8
- Tanggal: `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`

### Web dashboard blank

```bash
# Login dulu
curl http://localhost:8000/login

# Buat user jika belum ada
docker compose run --rm app python -m app.cli create-user
```

### Database error

```bash
# Cek migrasi
docker compose run --rm app python -m alembic current

# Jalankan migrasi
docker compose run --rm app python -m alembic upgrade head
```

---

## 🤝 Contributing

1. Fork repository
2. Buat branch fitur: `git checkout -b fitur/nama`
3. Commit: `git commit -m 'Add: fitur baru'`
4. Push: `git push origin fitur/nama`
5. Buat Pull Request

---

## 📄 License

MIT License - lihat file `LICENSE` untuk detail.

---

## 👏 Credits

- OCR: RapidOCR, EasyOCR
- Bot Framework: aiogram
- Web Framework: FastAPI
- Database: SQLAlchemy, SQLite
- Icons: Emoji native

---

**Catat v1.1.0** — Tracking keuangan yang simple dan powerful.
