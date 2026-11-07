# Changelog

Semua perubahan penting pada Catat didokumentasikan di file ini.
Format mengikuti Keep a Changelog dan project mengikuti Semantic Versioning.

## [1.2.0] - 2026-11-07

### Added

- REST API `/api/v1` untuk Hermes/agent eksternal.
- CRUD transaksi, dompet, kategori, budget, import CSV, dan summary via API.
- Dokumentasi API lengkap di [`docs/API_HERMES.md`](docs/API_HERMES.md).
- Saldo dompet dinamis dari transaksi dengan sinkronisasi otomatis.
- Import CSV round-trip dengan auto-create dompet dan kategori.
- Kolom `Jenis Dompet` dan `Waktu` pada CSV.
- Test regresi untuk delete flow, API, import/export, dan loading state.

### Changed

- Export difokuskan ke transaksi: `/export/transaksi.csv` dan Excel.
- Export format bank, export dompet, dan backup CSV terpisah dihapus.
- Dependency OCR dibuat eksplisit di `requirements.txt`.
- README diperbarui untuk Windows, Linux Docker, konfigurasi, API, dan upgrade.
- Loading form memakai `is-submitting` agar teks tombol tidak ikut berputar.

### Fixed

- Hapus akun sekarang menghapus seluruh data dan kembali ke register.
- Hapus dompet/kategori aman terhadap foreign key dan soft-deleted transaction.
- Jam transaksi tidak berubah menjadi `00:00` setelah import CSV.
- Transfer tetap memiliki dompet tujuan saat round-trip CSV.
- Import tidak salah membedakan `Jenis` dan `Jenis Dompet`.

### Removed

- Script diagnostic/eksperimen lama yang tidak digunakan.
- Database kosong/sisa test dari repository.
- Dokumentasi release lama yang duplikat.

## [1.1.0] - 2026-11-02

- Peningkatan UI grid dan format response bot.
- CRUD transaksi via bot.
- Filter periode dan peningkatan dashboard.
- CRUD kategori dan pengelolaan dompet.
- Budget tracking dan alert.

## [1.0.0]

- Release awal web dashboard dan Telegram bot.
- SQLite, OCR struk, parsing transaksi, budget, dan export laporan.

[1.2.0]: https://github.com/Heda312/expenses-tracker/releases/tag/v1.2.0
[1.1.0]: https://github.com/Heda312/expenses-tracker/releases/tag/v1.1.0
