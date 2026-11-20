# Release v1.3.0 — dokumen siap paste

**Tag:** `v1.3.0` (sudah ada di remote, menunjuk commit `da40284`)
**Judul release:** `v1.3.0 — Slim 1.44GB, bot package, glass UI beige × hijau`

Salin bagian di bawah garis ini ke kolom body release GitHub.

---

## Highlights

- **Image Docker 10.3GB → 1.44GB**: EasyOCR + PyTorch dihapus; RapidOCR (ONNX) jadi satu-satunya engine OCR (strategi dua pass raw → preprocess dipertahankan). Apt Dockerfile dipangkas ke 3 lib runtime.
- **Refactor bot**: `app/bot.py` (2.667 baris) dipecah menjadi package `app/bot/` (15 modul). Urutan registrasi handler diverifikasi identik dengan versi lama (19 message + 26 callback, termasuk filter/decorator).
- **UI baru**: glassmorphism beige × hijau (light only), font sistem tanpa Google Fonts, favicon & brand mark "C", palet kategori earthy yang konsisten di donut/legend/daftar kategori.
- **Dashboard**: kartu "Informasi Keuangan Lainnya" diganti **Ringkasan Periode** — savings rate, aman dibelanjakan/hari (+sisa hari), rata-rata pengeluaran harian + proyeksi, transaksi terbesar, total transaksi, hari aktif.
- **Dead code dibersihkan**: `services/llm.py`, `services/analytics.py`, `routers/dashboard_new.py`, parameter `use_llm`, skor kesehatan keuangan.
- **Kontrak API Hermes `/api/v1` tidak berubah** — siap untuk integrasi mobile ke depan.

## Perbedaan dengan v1.2.0

v1.2.0 adalah rilis **fitur integrasi**: REST API `/api/v1` untuk Hermes, saldo dompet dinamis + sinkronisasi, import CSV round-trip dengan auto-create dompet/kategori, dan export yang difokuskan ke transaksi. v1.3.0 adalah rilis **fondasi**: tidak menambah fitur integrasi baru, melainkan membuat aplikasi jauh lebih ringan, struktur kode lebih bersih, dan tampilan lebih enak dipakai — sekaligus menyiapkan fondasi untuk analisis finansial penuh di website dan aplikasi mobile ke depan.

| Aspek | v1.2.0 | v1.3.0 |
| --- | --- | --- |
| Fokus rilis | Fitur integrasi Hermes & CSV round-trip | Performa, struktur kode, UI/UX |
| Image Docker | 10.3GB (EasyOCR + PyTorch) | 1.44GB (RapidOCR ONNX saja) |
| OCR | Dua engine (EasyOCR + RapidOCR) | Satu engine, dua pass (raw → preprocess) |
| Kode bot | `app/bot.py` monolit 2.667 baris | Package `app/bot/` 15 modul, urutan handler identik |
| Dashboard | Kartu "Informasi Keuangan Lainnya" + skor kesehatan | Kartu "Ringkasan Periode" (6 metrik actionable) |
| UI | Tema lama, font Google, modal tanpa style | Glass beige × hijau light-only, font sistem, design token |
| API `/api/v1` | Diperkenalkan | Tidak berubah (kontrak beku) |
| Dead code | — | −3.861 baris (llm, analytics, dashboard_new, use_llm, health score) |

Total diff antar tag: 43 file, +3.590 / −3.861 baris.

## Changed

- Redesign UI: tema glassmorphism beige × hijau (light only), font sistem tanpa Google Fonts, favicon dan brand mark "C" baru.
- Dashboard: kartu "Informasi Keuangan Lainnya" diganti "Ringkasan Periode" (savings rate, aman dibelanjakan per hari, rata-rata harian + proyeksi, transaksi terbesar, total transaksi, hari aktif).
- Refactor: `app/bot.py` (2.667 baris) dipecah menjadi package `app/bot/` (15 modul); urutan registrasi handler dipertahankan persis.
- OCR: RapidOCR (ONNX) menjadi satu-satunya engine; strategi dua pass (raw → preprocess) dipertahankan.
- Dockerfile: library apt dipangkas ke kebutuhan runtime OCR saja.
- Warna kategori: palet earthy terkurasi, konsisten antara donut, legend, dan daftar kategori; kategori baru dari bot/import/API otomatis mendapat warna.
- Style inline di template base & categories dipindah ke `app.css` dengan design token.

## Removed

- Dependensi EasyOCR dan PyTorch (image Docker turun drastis).
- Dead code: `services/llm.py`, `services/analytics.py`, `routers/dashboard_new.py`, parameter `use_llm`, dan skor kesehatan keuangan.
- Header brand duplikat di layout mobile.

## Fixed

- Modal alert & kategori sebelumnya memakai variabel CSS yang tidak terdefinisi sehingga tampil tanpa style.
- Halaman login/register/setup masih memakai meta dark theme dan brand mark lama.
- Label baris Ringkasan Periode terpotong ellipsis di layar sempit; kini wrap rapi.

## Verification

- 60 unit/integration tests passed.
- Smoke test 17 halaman ALL OK pada database fresh.
- Skrip NLU bot offline ALL OK; urutan handler bot lama vs baru identik (nama + filter + sumber decorator).
- API Hermes live check: 401 tanpa token, shape `/api/v1/summary` unchanged, POST transaksi sukses dengan delta saldo persis.
- Image slim di-boot terpisah: health, login, migrasi Alembic, dan API summary normal pada DB fresh.
- Review visual screenshot semua halaman + layout mobile 390px.

## Upgrade notes

Tidak ada perubahan skema database dan tidak ada perubahan kontrak API. Deploy ulang cukup build image baru (`docker compose build && docker compose up -d`). Bot Telegram tetap harus jalan dengan `--workers 1`. Data lama aman: migrasi Alembic berjalan otomatis saat boot.