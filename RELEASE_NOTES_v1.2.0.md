# Catat v1.2.0 — Release Notes

**Tanggal rilis:** 7 November 2026
**Versi sebelumnya:** v1.1.0

Rilis ini berfokus pada **akurasi data keuangan**: saldo dompet kini sepenuhnya
dinamis, import/export CSV bisa round-trip, dan tersedia REST API untuk agent
eksternal. Selain itu sejumlah bug penting diperbaiki.

---

## Ringkasan Perubahan

| Area | Perubahan |
|---|---|
| Dompet | Saldo dinamis dari transaksi + sinkronisasi otomatis |
| Import/Export | CSV round-trip, jenis dompet & jam ikut terbawa |
| API | REST API baru `/api/v1` untuk agent Hermes |
| Bot | Hapus kategori/transaksi kini FK-safe |
| Bug fix | Hapus akun, loading spinner, jam hilang saat import |
| Docs | README baru + `docs/API_HERMES.md` |
| Cleanup | 10 file ad-hoc & 3 file DB sampah dihapus |

---

## ✨ Fitur Baru

### 1. Saldo Dompet Dinamis

Sebelumnya `opening_balance` menjadi angka yang dipatok. Sekarang saldo
**selalu dihitung dari transaksi**:

```
saldo = saldo_awal + pemasukan − pengeluaran − transfer_keluar + transfer_masuk
```

- Hanya transaksi `status = confirmed` dan belum dihapus yang dihitung.
- Halaman **Dompet** menampilkan rincian arus kas per dompet (masuk, keluar,
  jumlah transaksi, waktu sinkronisasi terakhir).
- Tombol **Sinkronkan saldo** (`POST /accounts/sync`) untuk hitung ulang manual.
- Cache `accounts.cached_balance` + `balance_updated_at` diperbarui otomatis
  setiap ada perubahan transaksi (web, bot, API, import).

Modul baru: `app/services/wallet.py` — satu sumber rumus saldo untuk web, bot,
dan API.

### 2. REST API untuk Agent Hermes

API baru di `/api/v1` dengan autentikasi Bearer token:

```env
HERMES_API_TOKEN="token-acak-panjang"
```

```http
Authorization: Bearer <HERMES_API_TOKEN>
```

Endpoint: transaksi, dompet, kategori, budget, import CSV, export, summary.

Fitur penting:
- **Auto-create** dompet & kategori dari nama — agent tidak perlu lookup dulu.
- Nominal menerima format bebas: `35000`, `"35rb"`, `"1,5jt"`.
- Dompet bisa dirujuk lewat `id` atau `name`.

Dokumentasi lengkap: [`docs/API_HERMES.md`](docs/API_HERMES.md) + Swagger di `/docs`.

### 3. Import CSV yang Benar-Benar Round-Trip

Export → import kembali menghasilkan data identik.

- **Dompet otomatis dibuat** dari kolom `Dompet` dan langsung terhubung ke transaksi.
- **Kategori otomatis dibuat** dari kolom `Kategori`.
- **Jenis dompet terbawa** lewat kolom `Jenis Dompet` (`bank`/`ewallet`/`cash`);
  kalau kosong, ditebak dari nama dompet (BCA → bank, GoPay → e-wallet, dst).
- **Jam transaksi tidak hilang** — kolom `Tanggal` + `Waktu` digabung kembali.
- **Transfer tetap transfer** — kolom `Dompet Tujuan` dipertahankan.
- Deteksi kolom dua tahap agar `Jenis Dompet` tidak tertukar dengan `Jenis`
  atau `Dompet`.
- Baris berawalan `#` diabaikan (bisa dipakai komentar).

Modul baru: `app/services/importer.py` — dipakai web, bot, dan API.

### 4. Pemisahan File Dompet & Transaksi (desain ulang)

Export kini **hanya berisi transaksi**. Export/import dompet terpisah dihapus —
dompet murni terbentuk dari transaksi. Ini menghilangkan duplikasi data dan
membuat satu sumber kebenaran.

---

## 🐛 Bug yang Diperbaiki

### Hapus akun gagal, tidak kembali ke register

- Form hapus akun tidak mengirim `confirm_password` padahal backend mewajibkannya
  → selalu ditolak. Sekarang form punya dua field konfirmasi.
- `PRAGMA foreign_keys = OFF` dijalankan di tengah transaksi (tidak berefek) dan
  tabel `categories` tidak ikut dihapus → `FOREIGN KEY constraint failed`.
  Sekarang memakai `delete()` SQLAlchemy dengan urutan aman.
- Ditambahkan dialog konfirmasi dan pesan error yang jelas.

### Teks berputar-putar (loading spinner)

- Class `.loading` di CSS adalah **spinner** (border-radius 50% + animasi
  rotate), tapi `loading.js` memasangnya ke `<form>` dan `<button>` sehingga
  seluruh teks tombol ikut berputar. State submit kini memakai class terpisah
  `is-submitting`.
- Overlay "Memindai struk..." punya dua nilai `display` dalam satu inline style
  (`none` lalu `flex`) sehingga selalu tampil. Sudah diperbaiki.
- Handler `pageshow` ditambahkan agar tombol tidak tertinggal disabled saat
  kembali dari bfcache.

### Jam transaksi hilang saat export/import

- Export menulis tanggal dan jam di kolom terpisah, tetapi importer hanya
  membaca `Tanggal` (`%Y-%m-%d`) → semua transaksi hasil import jadi `00:00`.
- Importer kini mengenali kolom `Waktu`/`Jam`/`Time` dan menggabungkannya dengan
  tanggal (dikonversi sebagai waktu lokal → UTC).

### Tidak bisa hapus dompet walau transaksi sudah dihapus

- Pengecekan menghitung **semua** baris termasuk yang sudah di-soft-delete.
- Kalau dipaksa, muncul `FOREIGN KEY constraint failed` karena
  `transactions.account_id` NOT NULL masih mereferensikan dompet.

Perbaikan (modul baru `app/services/cleanup.py`):
- Yang dihitung hanya transaksi **aktif**.
- Hapus dompet membersihkan baris transaksi mati yang menempel.
- Transfer dari dompet lain tetap utuh (`to_account_id` dilepas, bukan dihapus).
- Hapus kategori melepas referensi transaksi yang sudah dihapus, dan menghapus
  budget terkait.

### Hapus kategori via bot gagal

- Bot langsung `db.delete(category)` tanpa cek FK → error. Sekarang memakai
  `cleanup.delete_category()` dengan pesan jelas.

---

## 🔧 Perubahan Teknis

### Baru

| File | Fungsi |
|---|---|
| `app/services/wallet.py` | Saldo dompet dinamis, auto-create, sinkronisasi |
| `app/services/importer.py` | Import CSV round-trip |
| `app/services/cleanup.py` | Hapus dompet/kategori yang FK-safe |
| `app/routers/api.py` | REST API `/api/v1` |
| `app/schema_patch.py` | Penambal kolom untuk DB lama |
| `alembic/versions/b4_wallet_balance.py` | Migrasi kolom cache saldo |
| `docs/API_HERMES.md` | Dokumentasi API |
| `tests/conftest.py` | Isolasi DB per tes |

### Diubah

- `app/services/ledger.py` — `account_balances()` didelegasikan ke `wallet.py`
- `app/services/analytics.py` — saldo memakai `wallet.total_balance()`
- `app/services/export_formats.py` — CSV transaksi round-trip (format bank dihapus)
- `app/services/xlsx.py` — sheet Dompet dihapus, kolom Waktu & Jenis Dompet ditambah
- `app/routers/export.py` — hanya `/export.xlsx` dan `/export/transaksi.csv`
- `app/routers/accounts.py`, `categories.py`, `transactions.py` — sinkronisasi saldo
- `app/routers/settings_page.py` — hapus akun diperbaiki
- `app/bot.py` — `_import_csv` memakai service, sinkronisasi saldo
- `app/static/app.css`, `loading.js` — perbaikan loading state
- `app/models.py` — kolom `cached_balance`, `balance_updated_at`

### Dihapus

| Item | Alasan |
|---|---|
| `/export/umum.csv`, `/export/{bank}.csv` | Format bank tidak dipakai; digantikan CSV transaksi |
| `/export/dompet.csv`, `/export/backup.csv` | Export dompet terpisah tidak diperlukan |
| `build_bank_csv()`, `build_wallet_csv()`, `build_full_backup_csv()` | Tidak terpakai lagi |
| `check_schema.py`, `verify_clean.py`, `fix_alembic.py`, `delete_all_data.py` | Skrip ad-hoc satu kali pakai |
| `test_dashboard.py` | Skrip manual, bukan tes pytest |
| `CHANGES_SUMMARY.md`, `RELEASE_NOTES_v1.1.0.md`, `RELEASE_v1.1.0.md` | Digabung ke CHANGELOG & release notes |
| `scripts/check_schema.py`, `scripts/smoke_dashboard.py` | Duplikat/tidak terpakai |
| `app/app.db`, `data/catat.db`, `data/test_setup.db*` | File database sampah |

---

## 📦 Dependensi

### `requirements.txt`

- Tambah `opencv-python-headless>=4.9` dan `numpy>=1.24` (sebelumnya hanya
  terpasang sebagai transitif — sekarang eksplisit agar OCR stabil).
- Hapus `httpx` dari runtime (dipindah ke `requirements-dev.txt`; hanya dipakai
  `TestClient`).
- Semua paket diberi komentar pengelompokan.

### `requirements-dev.txt`

- Tambah `httpx>=0.27` (untuk `fastapi.testclient`).
- Hapus `requests` (tidak dipakai).
- Tambah `ruff>=0.5` untuk linting.

---

## 🚀 Instalasi

### Windows

```powershell
git clone https://github.com/Heda312/expenses-tracker.git
cd expenses-tracker
git checkout v1.2.0

py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
notepad .env
python -m uvicorn app.main:app --reload
```

> Windows butuh [Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe)
> untuk OCR.

### Linux (Docker)

```bash
git clone https://github.com/Heda312/expenses-tracker.git
cd expenses-tracker
git checkout v1.2.0

mkdir -p data/uploads
cp .env.example .env
nano .env

docker compose up -d --build
```

---

## 🔄 Upgrade dari v1.1.0

### Docker

```bash
git pull
git checkout v1.2.0
docker compose build --pull
docker compose up -d
```

### Manual

```bash
git pull
git checkout v1.2.0
source .venv/bin/activate      # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic upgrade head
# restart aplikasi
```

### Catatan upgrade

- Migrasi `b4_wallet_balance` menambahkan kolom `cached_balance` dan
  `balance_updated_at` ke tabel `accounts`. Dijalankan otomatis saat startup
  (`AUTO_MIGRATE=true`).
- Saldo semua dompet dihitung ulang otomatis saat aplikasi start — tidak perlu
  tindakan manual.
- **`/export/umum.csv` dan `/export/dompet.csv` sudah tidak ada.** Gunakan
  `/export/transaksi.csv`.
- Data lama tetap kompatibel; tidak ada perubahan format database yang merusak.

---

## ⚠️ Breaking Changes

| Perubahan | Dampak | Migrasi |
|---|---|---|
| Endpoint export bank dihapus | Script yang memanggil `/export/umum.csv` akan 404 | Pakai `/export/transaksi.csv` |
| Export dompet/backup dihapus | — | Dompet terbentuk otomatis saat import |
| `account_balances()` return dict diperluas | Kode yang bergantung pada key lama tetap jalan (key lama dipertahankan) | — |
| `build_workbook()` tanpa parameter `wallets` | Pemanggil lama perlu hapus argumen | — |

---

## 🧪 Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

**Hasil:** 60 tes lulus.

Cakupan tes baru:
- `tests/test_account_delete_export.py` (14 tes) — hapus akun, round-trip CSV,
  jam, jenis dompet, loading state
- `tests/test_delete_flow.py` (7 tes) — hapus dompet/kategori FK-safe
- `tests/conftest.py` — isolasi database per tes

---

## ⚠️ Catatan Penting

- **Gunakan `--workers 1`.** Bot Telegram berjalan dalam proses aplikasi; lebih
  dari satu worker menyebabkan bot menerima update ganda.
- **Backup dulu sebelum upgrade.** Walaupun migrasi aman, salinan
  `data/app.db` selalu disarankan.
- **OCR butuh dependency sistem.** Windows: VC++ Redistributable. Linux/Docker:
  `libgomp1`, `libgl1`, `libglib2.0-0`.

---

## 🙏 Kontribusi

Kontribusi terbuka. Jalankan `python -m pytest tests -q` sebelum mengirim PR.
