# Changelog

Semua perubahan penting pada project ini akan didokumentasikan di file ini.

Format berdasarkan [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
dan project ini mengikuti [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-11-02

### 🎉 Major Release - Kategori Custom & Import CSV

Ini adalah update besar yang memperkenalkan kategori yang bisa dikustomisasi penuh oleh user, import CSV otomatis, dan CRUD dinamis via bot Telegram.

### ✨ Added

#### CRUD Kategori Dinamis
- Kategori kosong saat setup awal (tanpa seed default)
- CRUD kategori lengkap via Telegram bot:
  - Tambah kategori: `tambah kategori Snack`
  - Hapus kategori: `hapus kategori Transport`
  - Ubah nama: `ubah kategori Makan jadi Makanan`
- Konfirmasi 2-step untuk tambah kategori (pilih jenis + konfirmasi final)
- Validasi penggunaan kategori di transaksi sebelum hapus
- Halaman `/categories` di web untuk manage kategori
- API endpoints: GET, POST, PUT, DELETE `/api/categories`

#### Import/Export CSV
- Import CSV via halaman Settings di web
- Import CSV via bot Telegram (command `/import`)
- Auto-detect format CSV (flexible column mapping)
- Auto-create kategori baru saat import
- Multiple date format support (YYYY-MM-DD, DD/MM/YYYY, dll)
- Error reporting detail per baris
- Success/error count summary

#### Bot Enhancements
- Query info dengan periode awareness:
  - `berapa transaksi bulan ini` vs `total transaksi`
  - `budget apa saja bulan lalu`
- Query breakdown baru:
  - `pengeluaran per kategori` - Top 10 kategori dengan persentase
  - `merchant terbanyak` - Most frequent merchants
  - `daftar akun` - List akun dengan saldo real-time
- Parser logic improved: prioritas query vs transaksi
- Budget edit dengan input manual (bukan preset amount)
- Konfirmasi interaktif untuk semua CRUD operations

#### UI/UX Improvements
- Filter periode transaksi (dropdown selector di halaman Transaksi)
- Alert modal global yang menggantikan native `alert()`
- Background gradient decoration di semua halaman
- Grid layout kategori responsive (2 kolom desktop, 1 kolom mobile)
- Modal close on backdrop click
- Button consistency dengan global theme
- Typography & spacing optimized untuk readability
- Style minimalis compact elegan di semua komponen

### 🔄 Changed

#### Breaking Changes
- **Kategori default dihapus** - User harus tambah kategori sendiri
- Database seed minimal (hanya akun Cash)

#### Non-Breaking Changes
- Parser natural language lebih akurat (nominal vs query)
- Budget preview dengan modal interaktif (edit kategori & nominal)
- Response format bot lebih konsisten (header center-aligned)
- Border radius uniform (8px-16px)
- Shadow & glow effects subtle

### 🐛 Fixed
- Bug `UnboundLocalError` di CRUD kategori handler
- Query "berapa sisa saldo" salah dikenali sebagai transaksi
- Parser tidak recognize query tanpa nominal
- Modal transparency issue di kategori page
- Button size inconsistency di halaman kategori
- Hover effect terlalu aggresive (putih semua)

### 🔧 Technical
- Tambah `Form()` parameter di FastAPI endpoints
- Better error logging di frontend (console.error)
- State management untuk budget nominal input
- Callback handlers untuk konfirmasi CRUD
- Period-aware query functions
- Merchant statistics aggregation
- Balance calculation dari ledger service

### 📚 Documentation
- README.md lengkap dengan panduan setup & fitur
- Format CSV untuk import
- Perintah bot Telegram comprehensive
- Troubleshooting guide
- Update & migration guide dari v1.x
- Contributing guidelines

### 🗂️ Files Changed
- `app/bot.py` - +1338 lines (CRUD, import, query enhancements)
- `app/seed.py` - Minimal seed (kategori dihapus)
- `app/main.py` - Register categories router
- `app/routers/categories.py` - NEW (CRUD API & page)
- `app/templates/categories.html` - NEW (kategori management UI)
- `app/templates/base.html` - Alert modal global & background decoration
- `app/templates/transactions.html` - Filter periode dropdown
- `app/templates/settings.html` - Import CSV section
- `README.md` - Complete rewrite untuk v2.0.0
- `CHANGELOG.md` - NEW (this file)

---

## [1.0.0] - 2024-XX-XX

### Initial Release
- Telegram bot dengan OCR struk
- Natural language input transaksi
- Web dashboard dengan budget tracking
- Multi-wallet support
- Export Excel & CSV
- Kategori seed default (28 kategori)
- Dark mode theme
