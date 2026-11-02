# Catat v1.0.0

## Ringkasan

Release pertama Catat, aplikasi pencatat keuangan pribadi dengan web dashboard dan Telegram bot.

Catat mendukung input transaksi manual, input melalui Telegram, upload foto struk, OCR otomatis, klasifikasi kategori dan dompet, dashboard analitik, budget, serta export Excel dan CSV.

## Fitur Utama

### Web Dashboard

- Dark theme responsif.
- Ringkasan pemasukan, pengeluaran, cashflow, dan saldo.
- Analisis berdasarkan kategori, merchant, dompet, dan periode.
- Grafik arus kas enam bulan.
- Donut chart kategori pengeluaran.
- Progress budget.
- Daftar transaksi terbaru.
- Dynamic masonry card layout.
- Layout otomatis menyesuaikan desktop, tablet, dan mobile.

### Analisis Keuangan

Dashboard menampilkan:

- Total pemasukan.
- Total pengeluaran.
- Cashflow bersih.
- Total saldo seluruh dompet.
- Rata-rata pengeluaran per hari kalender.
- Rata-rata pengeluaran per hari aktif.
- Jumlah hari aktif.
- Perubahan pengeluaran dibanding periode sebelumnya.
- Rasio tabungan.
- Transaksi terbesar.
- Merchant dengan pengeluaran terbesar.
- Dompet dengan pengeluaran terbesar.
- Kategori pengeluaran terbesar.
- Pengeluaran per dompet.
- Perbandingan pemasukan dan pengeluaran.

### Input Transaksi

- Input transaksi manual melalui website.
- Input transaksi melalui teks Telegram.
- Support transaksi pemasukan, pengeluaran, dan transfer.
- Draft transaksi membutuhkan konfirmasi sebelum disimpan.
- Deteksi otomatis nominal, jenis transaksi, merchant, kategori, dompet, tanggal, dan waktu.

Format nominal yang didukung:

```text
Rp 47.500
Rp. 47.500
IDR 47,500
50rb
1,5jt
47500
```

### OCR Struk

- Upload struk melalui website.
- Upload foto struk melalui Telegram.
- Upload dokumen gambar melalui Telegram.
- Format: JPG, JPEG, PNG, WEBP, BMP, dan TIFF.
- Resize dan kompresi gambar sebelum OCR.
- RapidOCR sebagai engine utama.
- EasyOCR sebagai fallback.
- Dukungan Bahasa Indonesia dan Inggris.
- Parsing nominal, merchant, tanggal, waktu, dompet, dan kategori.

Format waktu yang didukung:

```text
18:20
18:20:15
18.20
18.20.15
1820
182015
06:20 PM
06.20.15pm
```

Timezone receipt menggunakan `Asia/Jakarta`. Database menyimpan waktu dalam UTC dan mengonversinya saat ditampilkan.

### Telegram Bot

Command:

```text
/start
/help
/ringkasan
/status
/saldo
/budget
/pengeluaran
/pemasukan
/transaksi
/harian
/mingguan
/bulanan
```

Bot mendukung pertanyaan natural language:

```text
Gimana kondisi keuangan saya hari ini?
Berapa pengeluaran saya minggu ini?
Berapa pemasukan bulan lalu?
Spending bulan Oktober 2026 berapa?
```

Laporan menampilkan total dan jumlah transaksi pemasukan, pengeluaran, cashflow bersih, serta periode laporan.

Bot juga menerima foto dan file struk. Setiap hasil OCR dibuat sebagai draft dan harus dikonfirmasi melalui tombol Simpan, Ubah, atau Batal.

### Kategori

Kategori pengeluaran:

- Makan & Minum
- Transportasi
- Belanja
- Tagihan
- Kesehatan
- Hiburan
- Pendidikan
- Rumah Tangga
- Komunikasi
- Keuangan
- Pakaian
- Perawatan Diri
- Langganan
- Pajak & Administrasi
- Donasi & Zakat
- Hewan Peliharaan
- Anak
- Perjalanan
- Hadiah
- Lainnya

Kategori pemasukan:

- Gaji
- Bonus
- Pemasukan Lain
- Freelance
- Investasi
- Penjualan
- Cashback
- Bunga

Classifier menggunakan merchant memory, keyword rules, fuzzy matching, Ollama optional, lalu fallback `Lainnya`.

### Dompet

- Tunai.
- Rekening bank.
- E-wallet.
- Multiple wallet.
- Transfer antar dompet.
- Perhitungan saldo otomatis.

Alias dompet yang didukung meliputi BCA, Mandiri, BRI, BNI, BTN, QRIS, GoPay, DANA, OVO, ShopeePay, dan LinkAja.

### Budget

- Budget per kategori.
- Progress pemakaian budget.
- Sisa budget.
- Indikator budget terlampaui.
- Tampilan budget di dashboard.

### Export

Export tersedia dalam format:

- Excel.
- CSV transaksi.

Excel berisi sheet `Transaksi`, `Ringkasan`, dan `Budget`, dengan format Rupiah, freeze header, auto filter, styling header, serta chart pengeluaran per kategori.

CSV berisi:

```text
Tanggal
Waktu
Deskripsi
Debit
Kredit
Nominal
Saldo
Dompet
Kategori
Reference ID
```

### UI/UX

- Custom modal menggantikan browser `alert()` dan `confirm()`.
- Dropdown kategori dipisahkan menjadi Pengeluaran dan Pemasukan.
- Export menu menggunakan dropdown UI.
- Favicon huruf H dengan tema ungu gelap.
- Brand icon di sidebar dan mobile header.
- Dekorasi glow ungu dan cyan.
- Responsive layout.
- Dynamic masonry dashboard.
- Tidak menggunakan dependency JavaScript tambahan.

## OCR/parser only (LLM removed)

OCR/parser config:

## Deployment Docker

Project menyediakan Dockerfile Linux berbasis Python 3.12 slim, Docker Compose, persistent volume, dependency OCR Linux, healthcheck `/health`, auto migration Alembic, optional Cloudflare Tunnel, dan `.dockerignore`.

### Setup Linux

```bash
cp .env.example .env
mkdir -p data/uploads
chmod 700 data
```

Edit `.env`, lalu jalankan:

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f app
```

Cek healthcheck:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Cloudflare Tunnel optional:

```bash
TUNNEL_TOKEN=... docker compose --profile tunnel up -d
```

Backup:

```bash
docker compose stop app
tar -czf catat-backup-$(date +%F).tar.gz data/
docker compose start app
```

Update:

```bash
git pull origin main
docker compose build --pull
docker compose up -d
```

## Maintenance

- Test resmi berada di folder `tests/`.
- Script diagnostic berada di `scripts/check_transfers.py`.
- Script OCR eksperimen lama sudah dihapus.
- Database dan upload tidak masuk Docker image.
- `.env` tidak masuk repository.
- Data disimpan melalui volume `./data`.

## Known Limitations

- EasyOCR membutuhkan RAM lebih besar dibanding OCR berbasis binary.
- Ollama membutuhkan resource tambahan jika diaktifkan.
- Export bank spesifik belum dibuat; tersedia Excel dan CSV generik.
- Notifikasi budget Telegram membutuhkan scheduler production terpisah untuk deployment multi-worker.
- Multi-user belum menjadi mode utama.
- Aplikasi dioptimalkan untuk single-user.

## Technical Stack

- Python 3.12
- FastAPI
- SQLAlchemy
- SQLite
- Alembic
- Aiogram
- RapidOCR
- EasyOCR
- OpenCV
- OpenPyXL
- Ollama optional
- Docker Compose

## License

MIT
