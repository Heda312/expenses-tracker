# Catat — Expense Tracker

Aplikasi pencatat keuangan dengan input via Telegram bot dan web dashboard.

**Versi 1.1.0** — UI Grid Layout, response improved, CRUD transaksi via bot.

## Fitur

### Telegram Bot
- OCR struk dengan ekstraksi nominal otomatis
- Input transaksi via natural language
- CRUD kategori via chat
- Budget tracking per kategori
- Query info (saldo, budget, transaksi, dll)

### Web Dashboard
- Dashboard dengan ringkasan keuangan
- Manajemen transaksi (CRUD)
- Manajemen kategori custom
- Manajemen akun/dompet
- Import/Export CSV dan Excel
- Budget tracking dengan alert
- Filter periode transaksi
- Dark mode

## Quick Start

### Prasyarat
- Python 3.12+
- Docker & Docker Compose
- Token bot Telegram dari @BotFather

### Installasi dengan Docker

1. Clone repository
```bash
git clone https://github.com/Heda312/expenses-tracker.git
cd expenses-tracker
```

2. Setup environment
```bash
cp .env.example .env
mkdir -p data/uploads
chmod 700 data
# Edit .env sesuai kebutuhan
```

3. Build dan run
```bash
docker compose build
docker compose up -d
```

4. Cek status
```bash
docker compose ps
docker compose logs -f app
```

5. Akses di http://localhost:8000

## Setup Telegram Bot

1. Buat bot via @BotFather, dapatkan token
2. Dapatkan chat_id dari @userinfobot
3. Tambahkan ke `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_CHAT_ID=your_chat_id
```

Bot hanya akan merespons chat dari `TELEGRAM_ALLOWED_CHAT_ID` yang terdaftar.

## Perintah Bot Telegram

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
/kategori
```

### Budget
```
budget makanan 2jt
atur budget transportasi 500rb
/budget
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
/saldo
/budget
/ringkasan
/pengeluaran
/pemasukan
/transaksi
```

## Struktur File
```
expenses/
├── app/
│   ├── main.py          FastAPI app
│   ├── bot.py           Telegram bot logic
│   ├── models.py        SQLAlchemy models
│   ├── config.py        Configuration
│   ├── db.py            Database session
│   ├── security.py      Auth & password
│   ├── seed.py          Default data
│   ├── cli.py           CLI commands
│   ├── routers/         API endpoints
│   ├── services/        Business logic
│   └── templates/       Web templates
├── alembic/             Database migrations
├── data/                Database & uploads
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Tech Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy
- Database: SQLite dengan WAL mode
- Frontend: Jinja2, vanilla JS, modern CSS
- Bot: aiogram
- OCR: RapidOCR (fallback ke EasyOCR)

## Backup & Restore

Backup:
```bash
docker compose stop app
tar -czf backup-$(date +%Y%m%d).tar.gz data/
docker compose start app
```

Restore:
```bash
docker compose stop app
tar -xzf backup-*.tar.gz
docker compose start app
docker compose run --rm app python -m alembic upgrade head
docker compose up -d
```

## Troubleshooting

**Bot tidak merespons?**
- Cek `TELEGRAM_ALLOWED_CHAT_ID` di `.env`
- Pastikan bot running: `docker compose logs bot`

**OCR gagal?**
- Gunakan Python <3.13
- Foto harus jelas dan terang

**Import CSV gagal?**
- Cek format header CSV
- Pastikan encoding UTF-8

**Web dashboard blank?**
- Akses `/login` dan login dulu
- Pastikan user sudah dibuat via CLI
- Cek browser console

## Contributing

1. Fork repository
2. Buat branch fitur
3. Commit perubahan
4. Push ke branch
5. Buat Pull Request

## License

MIT License - lihat file LICENSE untuk detail.

## Credits

- OCR: RapidOCR, EasyOCR
- Bot Framework: aiogram
- Web Framework: FastAPI
- Database: SQLAlchemy, SQLite
