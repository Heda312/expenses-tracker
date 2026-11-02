# Catat — Expense Tracker Sederhana

Aplikasi pencatat keuangan dengan input via Telegram bot (foto struk + teks natural) dan web dashboard interaktif.

**Versi 2.0.0** — Update besar dengan kategori custom, import CSV, dan CRUD dinamis via bot.

## ✨ Fitur Utama

### Telegram Bot
- 📸 **OCR Struk** - Upload foto, ekstrak nominal otomatis
- 💬 **Natural Language** - "makan siang 35rb", "gaji 8jt masuk bca"
- 📁 **CRUD Kategori** - Tambah, hapus, ubah kategori via chat
- 📊 **Query Info** - Tanya status keuangan, budget, transaksi
- 💼 **Budget Management** - Atur budget dengan konfirmasi interaktif
- 📥 **Import CSV** - Upload transaksi bulk via bot

### Web Dashboard
- 🎨 **UI Modern** - Design minimalis, elegan, responsive
- 📁 **Kategori Custom** - Kelola kategori sendiri, tanpa seed default
- 📥 **Import/Export** - Import CSV, export Excel & CSV
- 🔍 **Filter Periode** - Lihat transaksi per bulan atau semua periode
- 💰 **Multi-Wallet** - Tunai, bank, e-wallet
- 📊 **Budget Tracking** - Progress bar per kategori
- 🌙 **Dark Mode** - Theme gelap by default

## 🚀 Quick Start

### Prasyarat
- Python 3.11+
- Docker & Docker Compose (untuk production)
- Token bot Telegram dari @BotFather
- OCR: RapidOCR, EasyOCR (fallback)

### Setup Development

```bash
# 1. Clone repository
git clone <repo-url>
cd expenses

# 2. Install dependencies
python -m pip install -r requirements-dev.txt

# 3. Setup environment
cp .env.example .env
# Edit .env: SECRET_KEY, TELEGRAM_BOT_TOKEN, dll

# 4. Migrasi database
python -m alembic upgrade head

# 5. Buat user
python -m app.cli create-user --email user@example.com

# 6. Jalankan server
uvicorn app.main:app --reload

# 7. Akses dashboard
# http://localhost:8000
```

### Deploy dengan Docker

```bash
# 1. Setup environment
cp .env.example .env
mkdir -p data/uploads
chmod 700 data
# Edit .env sesuai kebutuhan

# 2. Build dan run
docker compose build
docker compose up -d

# 3. Cek status
docker compose ps
docker compose logs -f app

# 4. Akses di http://IP_SERVER:8000
```

## 📱 Setup Telegram Bot

1. Buat bot via @BotFather, dapatkan token
2. Dapatkan chat_id dari @userinfobot
3. Tambahkan ke `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_CHAT_ID=your_chat_id
```

Bot hanya akan merespons chat dari `TELEGRAM_ALLOWED_CHAT_ID` yang terdaftar.

## 💬 Perintah Bot Telegram

### Transaksi
```
makan siang 35rb
parkir 5rb pake gopay
gaji 8jt masuk bca
```

### CRUD Kategori
```
tambah kategori Snack
hapus kategori Transport
ubah kategori Makan jadi Makanan
/kategori                    # List semua kategori
```

### Budget
```
budget makanan 2jt
atur budget transportasi 500rb
/budget                      # Status budget semua kategori
```

### Query Info
```
berapa sisa saldo
berapa kategori
kategori apa saja
berapa transaksi bulan ini
budget apa saja
pengeluaran per kategori
merchant terbanyak
```

### Laporan
```
/ringkasan                   # Kondisi keuangan bulan ini
/saldo                       # Saldo semua dompet
/pengeluaran                 # Total pengeluaran
/pemasukan                   # Total pemasukan
```

### Import
```
/import                      # Instruksi import CSV
# Upload file CSV dengan format yang didukung
```

## 📊 Format CSV untuk Import

### Header (opsional, auto-detect):
```csv
tanggal,nominal,kategori,merchant,dompet
```

### Contoh Data:
```csv
2026-11-01,50000,Makanan,Indomaret,Cash
01/11/2026,100000,Transport,Grab,GoPay
2026-11-02,35000,Snack,,Tunai
```

**Format yang didukung:**
- Tanggal: `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `YYYY/MM/DD`
- Kategori otomatis dibuat jika belum ada
- Kolom opsional: merchant, dompet (default ke akun pertama)

## 🗂️ Struktur Project

```
expenses/
├── app/
│   ├── main.py              # FastAPI app entry
│   ├── bot.py               # Telegram bot logic
│   ├── models.py            # SQLAlchemy models
│   ├── config.py            # Configuration
│   ├── db.py                # Database session
│   ├── security.py          # Auth & password
│   ├── seed.py              # Default data (minimal)
│   ├── cli.py               # CLI commands
│   ├── routers/
│   │   ├── auth.py          # Login/logout
│   │   ├── dashboard.py     # Dashboard page
│   │   ├── transactions.py  # Transaksi CRUD
│   │   ├── accounts.py      # Wallet management
│   │   ├── budgets.py       # Budget tracking
│   │   ├── categories.py    # Category CRUD (NEW)
│   │   ├── export.py        # Excel/CSV export
│   │   ├── ocr.py           # Receipt OCR
│   │   └── settings_page.py # Settings & import (NEW)
│   ├── services/
│   │   ├── money.py         # Currency parser
│   │   ├── dates.py         # Date utilities
│   │   ├── ocr.py           # OCR engines
│   │   ├── classify.py      # Category detection
│   │   ├── ledger.py        # Balance calculation
│   │   └── budget_alerts.py # Budget notifications
│   ├── templates/           # Jinja2 templates
│   │   ├── base.html        # Base layout (NEW alert modal)
│   │   ├── dashboard.html   # Dashboard
│   │   ├── transactions.html # Transaction list (NEW filter)
│   │   ├── categories.html  # Category management (NEW)
│   │   ├── budgets.html     # Budget page
│   │   └── settings.html    # Settings (NEW import section)
│   └── static/
│       ├── app.css          # Global styles
│       └── app.js           # Global scripts
├── alembic/                 # Database migrations
├── tests/                   # Unit tests
├── data/                    # SQLite + uploads (gitignored)
├── requirements.txt         # Production deps
├── requirements-dev.txt     # Dev deps
├── Dockerfile              
├── docker-compose.yml      
└── README.md
```

## 🔧 Teknologi

- **Backend**: FastAPI, SQLAlchemy, Alembic
- **Bot**: aiogram 3.x
- **OCR**: RapidOCR, EasyOCR (fallback)
- **OCR**: RapidOCR, EasyOCR (fallback)
- **Database**: SQLite dengan WAL mode
- **Frontend**: Jinja2, vanilla JS, modern CSS

## 🎯 Fitur Baru v2.0.0

### CRUD Kategori Dinamis
- ✅ Kategori kosong saat setup awal
- ✅ User bisa tambah kategori custom
- ✅ Edit dan hapus kategori via web & bot
- ✅ Konfirmasi 2-step untuk tambah (pilih jenis + konfirmasi)
- ✅ Validasi penggunaan kategori di transaksi

### Import/Export Enhanced
- ✅ Import CSV via web (halaman Settings)
- ✅ Import CSV via bot Telegram
- ✅ Auto-detect format CSV
- ✅ Auto-create kategori baru saat import
- ✅ Error reporting detail per baris

### Bot Enhancements
- ✅ Query info dengan periode awareness
- ✅ "berapa transaksi bulan lalu"
- ✅ "pengeluaran per kategori"
- ✅ "merchant terbanyak"
- ✅ Parser logic improved (prioritas query vs transaksi)
- ✅ Budget edit dengan input manual (bukan preset)

### UI/UX Improvements
- ✅ Filter periode transaksi (dropdown selector)
- ✅ Alert modal global (replace native alert)
- ✅ Background gradient decoration
- ✅ Grid layout kategori responsive
- ✅ Modal close on backdrop click
- ✅ Button consistency dengan global theme
- ✅ Typography & spacing optimized

## 📦 Backup & Restore

### Backup
```bash
# Stop aplikasi
docker compose stop app

# Backup database dan uploads
tar -czf catat-backup-$(date +%F).tar.gz data/

# Start kembali
docker compose start app
```

### Restore
```bash
docker compose stop app
tar -xzf catat-backup-YYYY-MM-DD.tar.gz
docker compose start app
```

## 🔄 Update dari v1.x ke v2.0.0

```bash
# 1. Backup data
docker compose stop app
tar -czf backup-pre-v2.tar.gz data/

# 2. Pull update
git pull origin main

# 3. Rebuild
docker compose build --pull

# 4. Migrasi (jika ada)
docker compose run --rm app python -m alembic upgrade head

# 5. Start
docker compose up -d

# 6. Cek logs
docker compose logs -f app
```

**Breaking Changes:**
- Kategori default dihapus - user perlu tambah kategori sendiri
- Database seed minimal (hanya akun Cash)

## 🐛 Troubleshooting

**Bot tidak merespons?**
- Cek `TELEGRAM_ALLOWED_CHAT_ID` di `.env`
- Pastikan bot running: `docker compose logs bot`

**OCR gagal?**
- Gunakan Python <3.13
- Foto harus jelas dan terang
- RapidOCR akan fallback ke EasyOCR

**Import CSV gagal?**
- Cek format header CSV
- Pastikan encoding UTF-8
- Lihat error detail di response

**Web dashboard blank?**
- Akses `/login` dan login dulu
- Pastikan user sudah dibuat via CLI
- Cek browser console untuk error

**Database error?**
- Pastikan migrasi sudah dijalankan: `alembic upgrade head`
- Cek `DATABASE_URL` di `.env`
- Pastikan folder `data/` writeable

## 📝 Contributing

1. Fork repository
2. Buat branch fitur: `git checkout -b feature/nama-fitur`
3. Commit perubahan: `git commit -m 'Add: fitur baru'`
4. Push ke branch: `git push origin feature/nama-fitur`
5. Buat Pull Request

## 📄 License

MIT License - lihat file LICENSE untuk detail.

## 🙏 Credits

- OCR: RapidOCR, EasyOCR
- Bot Framework: aiogram
- Web Framework: FastAPI
- Icons: Emoji native

---

**Dibuat dengan ❤️ untuk tracking keuangan pribadi yang simple dan powerful**
