# Catat v1.2.0 - Release Notes

**Tanggal rilis:** 7 November 2026`n**Versi sebelumnya:** v1.1.0

## Highlights

- REST API `/api/v1` untuk Hermes agent.
- Saldo dompet dinamis berdasarkan transaksi.
- Import CSV otomatis membuat dompet dan kategori.
- Jenis dompet (`cash`, `bank`, `ewallet`) ikut tersimpan di CSV.
- Jam transaksi tetap akurat saat export/import.
- Export disederhanakan menjadi transaksi CSV dan Excel.
- Perbaikan delete account, delete wallet/category, loading spinner, dan FK.

## Breaking Changes

- Endpoint export format bank seperti `/export/umum.csv` dihapus.
- Endpoint export dompet dan backup CSV terpisah dihapus.
- Gunakan `/export/transaksi.csv` untuk export yang bisa di-import ulang.
- Untuk integrasi Hermes, gunakan `/api/v1` dan `HERMES_API_TOKEN`.

## Upgrade dari v1.1.0

### Docker/Linux

```bash
git pull
git checkout v1.2.0
docker compose build --pull
docker compose up -d
```

### Windows/Linux manual

```bash
git pull
git checkout v1.2.0
# aktifkan .venv terlebih dahulu
pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Migrasi `b4_wallet_balance` menambahkan cache saldo dompet. Aplikasi juga
menghitung ulang saldo saat startup.

## Verifikasi

- 60 test lulus.
- API, import/export, delete flow, waktu transaksi, dan loading state diuji.
- Dokumentasi API tersedia di `docs/API_HERMES.md`.
