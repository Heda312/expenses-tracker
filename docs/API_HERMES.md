# Catat API v1 — Dokumentasi untuk Hermes Agent

Dokumentasi REST API Catat untuk integrasi bot/agent eksternal (Hermes).

- **Base URL**: `http://127.0.0.1:8000` (ganti sesuai host Anda)
- **Prefix API**: `/api/v1`
- **Format**: JSON (kecuali upload file)
- **Swagger interaktif**: `http://127.0.0.1:8000/docs`

---

## Daftar Isi

- [Autentikasi](#1-autentikasi)
- [Konvensi Penting](#2-konvensi-penting)
- [Model Data](#3-model-data)
- [Endpoint](#4-endpoint)
- [Kode Error](#5-kode-error)
- [Catatan untuk Agent](#6-catatan-untuk-agent)
- [Referensi Cepat](#7-referensi-cepat)

---

## 1. Autentikasi

Set token di file `.env` aplikasi:

```env
HERMES_API_TOKEN="token-acak-panjang"
```

Generate token yang aman:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Lalu kirim di **setiap** request:

```http
Authorization: Bearer <HERMES_API_TOKEN>
```

Catatan:

- Token salah atau tidak ada -> `401 Unauthorized`
- Kalau `HERMES_API_TOKEN` kosong di `.env`, akses token dinonaktifkan (hanya sesi login website yang bisa memakai API)
- `GET /api/v1/health` tidak butuh autentikasi

---

## 2. Konvensi Penting

### Nominal uang

Semua nominal adalah **integer rupiah** (tanpa desimal, tanpa titik/koma).

Saat **mengirim** nominal, API menerima format bebas dan mem-parsingnya:

| Input | Hasil |
|---|---|
| `35000` | 35000 |
| `"35rb"` | 35000 |
| `"35.000"` | 35000 |
| `"Rp 47.500"` | 47500 |
| `"1,5jt"` | 1500000 |

Saat **menerima** response, nominal selalu integer: `"amount": 35000`.

### Tanggal & waktu

- Kirim dalam **ISO 8601**: `"2026-11-07T14:30:00"` atau `"2026-11-07 14:30:00"`
- Tanpa timezone -> dianggap **waktu lokal** (`Asia/Jakarta` default)
- Boleh dengan timezone: `"2026-11-07T14:30:00+07:00"` atau `"...Z"`
- Kosong -> dipakai waktu sekarang
- Response menyertakan dua versi: `occurred_at` (UTC) dan `occurred_at_local` (waktu lokal)

### Dompet & kategori otomatis

Field `account` dan `category` (berupa **nama**, bukan id) akan **membuat data baru** kalau belum ada. Ini memudahkan agent: tidak perlu cek dulu.

Kalau tidak ingin auto-create, set `"create_missing": false` -> akan `404` jika tidak ditemukan.

### Saldo dompet bersifat dinamis

Saldo **tidak pernah** disimpan sebagai angka tetap. Selalu dihitung dari transaksi:

```
saldo = saldo_awal + pemasukan - pengeluaran - transfer_keluar + transfer_masuk
```

Hanya transaksi `status = "confirmed"` dan belum dihapus yang dihitung. Jadi setelah create/update/delete transaksi, saldo langsung berubah.

### Soft delete

`DELETE /transactions/{id}` default-nya **soft delete** (`deleted_at` diisi). Gunakan `?hard=true` untuk hapus permanen.

---

## 3. Model Data

### Transaction

```json
{
  "id": 12,
  "kind": "expense",
  "amount": 35000,
  "account_id": 1,
  "account": "BCA",
  "to_account_id": null,
  "to_account": null,
  "category_id": 3,
  "category": "Makanan",
  "merchant": "Indomaret",
  "note": null,
  "occurred_at": "2026-11-07T07:30:00",
  "occurred_at_local": "2026-11-07T14:30:00+07:00",
  "status": "confirmed",
  "source": "hermes",
  "deleted_at": null,
  "created_at": "2026-11-07T07:30:00",
  "updated_at": "2026-11-07T07:30:00"
}
```

| Field | Tipe | Keterangan |
|---|---|---|
| `kind` | string | `expense` \| `income` \| `transfer` |
| `amount` | integer | Nominal rupiah, selalu > 0 |
| `account_id` / `account` | int / string | Dompet asal |
| `to_account_id` / `to_account` | int / string \| null | Dompet tujuan (hanya `transfer`) |
| `category_id` / `category` | int / string \| null | Kategori (null untuk transfer) |
| `merchant` | string \| null | Nama toko/merchant, maks 120 karakter |
| `note` | string \| null | Catatan, maks 500 karakter |
| `status` | string | `pending` \| `confirmed` \| `rejected` |

**Penting:** transaksi `pending` **tidak** memengaruhi saldo. Pakai `confirmed` (default) untuk langsung masuk laporan.

### Account (Dompet)

```json
{
  "id": 1,
  "name": "BCA",
  "kind": "bank",
  "archived": false,
  "opening_balance": 100000,
  "income": 3000000,
  "expense": 150000,
  "transfer_in": 500000,
  "transfer_out": 0,
  "transaction_count": 3,
  "balance": 3450000,
  "balance_updated_at": "2026-11-07T07:30:00"
}
```

`kind` (jenis dompet): `cash` (tunai) \| `bank` \| `ewallet` (e-wallet).

Kalau `kind` tidak diisi saat membuat dompet, API menebak dari nama:

| Pola nama | Jenis |
|---|---|
| `bca`, `mandiri`, `bri`, `bni`, `cimb`, `jago`, `seabank`, `bank`, `rekening` | `bank` |
| `gopay`, `ovo`, `dana`, `shopeepay`, `linkaja`, `qris`, `dompet digital` | `ewallet` |
| lainnya (`Cash`, `Dompet Harian`, `Uang Saku`) | `cash` |

### Category (Kategori)

```json
{
  "id": 3,
  "name": "Makanan",
  "kind": "expense",
  "color": "#f5f0c4",
  "sort_order": 1
}
```

---

## 4. Endpoint

### Health & Ringkasan

#### `GET /api/v1/health`

Cek API hidup. **Tidak butuh auth.**

```bash
curl http://127.0.0.1:8000/api/v1/health
```

```json
{"status": "ok", "app": "Catat", "time": "2026-11-07T07:30:00"}
```

#### `GET /api/v1/summary`

Ringkasan total saldo + semua dompet.

```bash
curl http://127.0.0.1:8000/api/v1/summary \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "total_balance": 3500000,
  "wallets": [
    {"id": 1, "name": "BCA", "kind": "bank", "balance": 3450000, "transaction_count": 3},
    {"id": 2, "name": "GoPay", "kind": "ewallet", "balance": 50000, "transaction_count": 1}
  ],
  "transaction_count": 4
}
```

---

### Transaksi

#### `GET /api/v1/transactions`

List transaksi dengan filter & pagination.

| Parameter | Tipe | Default | Keterangan |
|---|---|---|---|
| `account_id` | int | - | Filter dompet (sebagai asal **atau** tujuan) |
| `category_id` | int | - | Filter kategori |
| `kind` | string | - | `expense` \| `income` \| `transfer` |
| `status` | string | - | `pending` \| `confirmed` \| `rejected` |
| `q` | string | - | Cari di merchant & note |
| `start` | string | - | Tanggal awal `YYYY-MM-DD` (lokal) |
| `end` | string | - | Tanggal akhir `YYYY-MM-DD` (lokal, inklusif) |
| `limit` | int | 50 | 1-500 |
| `offset` | int | 0 | Untuk pagination |
| `include_deleted` | bool | false | Sertakan yang sudah dihapus |

```bash
curl "http://127.0.0.1:8000/api/v1/transactions?start=2026-11-01&end=2026-11-30&kind=expense&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "total": 2,
  "limit": 20,
  "offset": 0,
  "transactions": [ { "...": "..." } ]
}
```

#### `POST /api/v1/transactions`

Buat transaksi baru. **Status `201 Created`.**

| Field | Tipe | Wajib | Default | Keterangan |
|---|---|---|---|---|
| `kind` | string | - | `expense` | `expense` \| `income` \| `transfer` |
| `amount` | int/string | ya | - | Nominal (format bebas: `35000`, `"35rb"`) |
| `account_id` | int | - | - | Id dompet |
| `account` | string | - | - | Nama dompet (auto-create) |
| `to_account_id` | int | - | - | Untuk `transfer` |
| `to_account` | string | - | - | Untuk `transfer` (auto-create) |
| `category_id` | int | - | - | Id kategori |
| `category` | string | - | - | Nama kategori (auto-create) |
| `merchant` | string | - | - | Maks 120 karakter |
| `note` | string | - | - | Maks 500 karakter |
| `occurred_at` | string | - | sekarang | ISO 8601 |
| `status` | string | - | `confirmed` | `pending` \| `confirmed` \| `rejected` |
| `create_missing` | bool | - | `true` | Auto-create dompet/kategori |

> **Catatan:** kalau `account_id` dan `account` sama-sama kosong, dipakai dompet aktif pertama. Untuk `transfer`, `to_account` wajib berbeda dari dompet asal.

Contoh pengeluaran:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/transactions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "expense",
    "amount": "35rb",
    "account": "BCA",
    "category": "Makanan",
    "merchant": "Indomaret",
    "occurred_at": "2026-11-07T14:30:00"
  }'
```

Contoh pemasukan:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/transactions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"income","amount":8000000,"account":"BCA","category":"Gaji","merchant":"Kantor"}'
```

Contoh transfer antar dompet:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/transactions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"transfer","amount":500000,"account":"BCA","to_account":"GoPay"}'
```

#### `GET /api/v1/transactions/{id}`

Detail satu transaksi.

```bash
curl http://127.0.0.1:8000/api/v1/transactions/12 \
  -H "Authorization: Bearer $TOKEN"
```

#### `PATCH /api/v1/transactions/{id}`

Ubah sebagian field. Kirim hanya field yang berubah.

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/transactions/12 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount": 50000, "category": "Transport"}'
```

Field yang bisa diubah: `kind`, `amount`, `account_id`, `account`, `to_account_id`, `to_account`, `category_id`, `category`, `merchant`, `note`, `occurred_at`, `status`.

#### `DELETE /api/v1/transactions/{id}`

Hapus transaksi (soft delete).

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/transactions/12 \
  -H "Authorization: Bearer $TOKEN"
```

Hapus permanen:

```bash
curl -X DELETE "http://127.0.0.1:8000/api/v1/transactions/12?hard=true" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"success": true, "hard": false, "id": 12}
```

---

### Dompet

#### `GET /api/v1/accounts`

Semua dompet + saldo terkini.

| Parameter | Tipe | Default | Keterangan |
|---|---|---|---|
| `include_archived` | bool | `true` | Sertakan dompet yang diarsipkan |

```bash
curl http://127.0.0.1:8000/api/v1/accounts \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "accounts": [
    {
      "id": 1, "name": "BCA", "kind": "bank", "archived": false,
      "opening_balance": 100000, "income": 3000000, "expense": 150000,
      "transfer_in": 500000, "transfer_out": 0,
      "transaction_count": 3, "balance": 3450000,
      "balance_updated_at": "2026-11-07T07:30:00"
    }
  ],
  "total_balance": 3450000
}
```

#### `POST /api/v1/accounts`

Buat dompet baru. **Status `201`.**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/accounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "GoPay", "kind": "ewallet", "opening_balance": 0}'
```

| Field | Tipe | Wajib | Keterangan |
|---|---|---|---|
| `name` | string | ya | Maks 80 karakter |
| `kind` | string | - | `cash` \| `bank` \| `ewallet` (kosong = ditebak dari nama) |
| `opening_balance` | int/string | - | Saldo awal |

Nama duplikat -> `409 Conflict`.

#### `GET /api/v1/accounts/{id}`

Detail dompet + rincian arus kas (`income`, `expense`, `transfer_in`, `transfer_out`, `transaction_count`).

#### `PATCH /api/v1/accounts/{id}`

Ubah dompet.

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/accounts/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "BCA Utama", "kind": "bank", "archived": false}'
```

#### `DELETE /api/v1/accounts/{id}`

Hapus dompet.

| Parameter | Tipe | Default | Keterangan |
|---|---|---|---|
| `force` | bool | `false` | `true` = hapus juga transaksi yang masih aktif |

```bash
# Gagal (409) kalau masih ada transaksi aktif
curl -X DELETE http://127.0.0.1:8000/api/v1/accounts/1 \
  -H "Authorization: Bearer $TOKEN"

# Paksa hapus beserta transaksinya
curl -X DELETE "http://127.0.0.1:8000/api/v1/accounts/1?force=true" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"success": true, "deleted_transactions": 3, "detached_transfers": 0}
```

Transaksi yang sudah di-soft-delete ikut dibersihkan. Kalau dompet hanya jadi **tujuan** transfer, referensinya dilepas (`to_account_id = null`) sehingga riwayat transfer dari dompet lain tetap ada.

#### `POST /api/v1/accounts/sync`

Hitung ulang saldo semua dompet dari transaksi.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/accounts/sync \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"success": true, "accounts": [{"id": 1, "name": "BCA", "balance": 3450000}]}
```

---

### Kategori

#### `GET /api/v1/categories`

| Parameter | Tipe | Keterangan |
|---|---|---|
| `kind` | string | Filter `expense` \| `income` |

```bash
curl "http://127.0.0.1:8000/api/v1/categories?kind=expense" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"categories": [{"id": 3, "name": "Makanan", "kind": "expense", "color": "#f5f0c4", "sort_order": 1}]}
```

#### `POST /api/v1/categories`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/categories \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Transport", "kind": "expense", "color": "#38bdf8"}'
```

`color` opsional (otomatis dari nama kalau kosong). Nama duplikat -> `409`.

#### `PATCH /api/v1/categories/{id}`

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/categories/3 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Makan & Minum"}'
```

#### `DELETE /api/v1/categories/{id}`

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/categories/3 \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"success": true, "detached_transactions": 0, "deleted_budgets": 0}
```

Kalau kategori masih dipakai transaksi **aktif** -> `409`. Kalau hanya dipakai transaksi yang sudah dihapus, referensinya dilepas dan kategori terhapus.

---

### Budget

#### `GET /api/v1/budgets`

| Parameter | Tipe | Default | Keterangan |
|---|---|---|---|
| `period` | string | bulan ini | Format `YYYY-MM` |

```bash
curl "http://127.0.0.1:8000/api/v1/budgets?period=2026-11" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "period": "2026-11",
  "budgets": [
    {
      "id": 1, "category_id": 3, "name": "Makanan", "color": "#f5f0c4",
      "amount": 1000000, "spent": 350000, "remaining": 650000,
      "pct": 35, "over": false
    }
  ]
}
```

---

### Import CSV

#### `POST /api/v1/import/csv`

Upload file CSV (multipart). **Status `201`.**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/import/csv \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@transaksi.csv"
```

#### `POST /api/v1/import/csv/text`

Kirim CSV sebagai string JSON (lebih praktis untuk agent).

```bash
curl -X POST http://127.0.0.1:8000/api/v1/import/csv/text \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "csv": "Tanggal,Waktu,Jenis,Nominal,Kategori,Merchant,Dompet,Jenis Dompet\n2026-11-07,14:30:00,Pengeluaran,15000,Makanan,Indomaret,BCA,bank\n"
  }'
```

**Response:**

```json
{
  "success": true,
  "imported": 1,
  "errors": 0,
  "accounts_created": ["BCA"],
  "categories_created": ["Makanan"],
  "messages": [],
  "wallets": [{"id": 1, "name": "BCA", "balance": 15000}],
  "total_balance": 15000
}
```

**Format CSV yang dikenali** (nama kolom dideteksi otomatis, tidak peka huruf besar/kecil):

| Kolom | Wajib | Keterangan |
|---|---|---|
| `Tanggal` / `Date` | - | `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, dst. |
| `Waktu` / `Jam` / `Time` | - | `HH:MM` atau `HH:MM:SS` (digabung dengan Tanggal) |
| `Jenis` / `Type` / `Kind` | - | Pengeluaran/Pemasukan/Transfer, atau debit/kredit |
| `Nominal` / `Amount` / `Jumlah` | ya | Format bebas (`15000`, `15.000`, `15rb`) |
| `Kategori` / `Category` | - | Auto-create kalau belum ada |
| `Merchant` / `Keterangan` / `Deskripsi` | - | Nama toko |
| `Dompet` / `Wallet` / `Account` / `Rekening` | - | Auto-create kalau belum ada |
| `Jenis Dompet` / `Wallet Type` | - | `bank`/`Bank`, `ewallet`/`E-wallet`, `cash`/`Tunai` |
| `Dompet Tujuan` / `Ke Dompet` | - | Untuk baris transfer |

Catatan:

- Baris yang diawali `#` diabaikan (bisa dipakai komentar)
- Tanpa kolom `Jenis Dompet`, jenis dompet ditebak dari nama dompet
- Setelah import, saldo semua dompet dihitung ulang otomatis

---

### Export

#### `GET /api/v1/export/transactions`

Ekspor transaksi sebagai JSON (semua waktu, hanya `confirmed`).

| Parameter | Tipe | Keterangan |
|---|---|---|
| `account_id` | int | Filter dompet |

```bash
curl http://127.0.0.1:8000/api/v1/export/transactions \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "count": 4,
  "transactions": [ { "...": "..." } ],
  "wallets": [{"id": 1, "name": "BCA", "balance": 3450000}]
}
```

---

## 5. Kode Error

| Kode | Arti | Contoh penyebab |
|---|---|---|
| `200` | OK | - |
| `201` | Created | Transaksi/dompet/kategori/import berhasil dibuat |
| `400` | Bad Request | Nominal tidak valid, transfer tanpa dompet tujuan, CSV rusak |
| `401` | Unauthorized | Token tidak ada / salah |
| `404` | Not Found | Id tidak ditemukan, `create_missing=false` tapi nama tidak ada |
| `409` | Conflict | Nama dompet/kategori duplikat, dompet masih punya transaksi aktif |
| `422` | Unprocessable | Validasi body gagal (field wajib kosong, tipe salah) |
| `500` | Server Error | Bug internal |

Format error:

```json
{"detail": "Dompet masih punya 3 transaksi aktif. Hapus transaksinya dulu atau pakai ?force=true."}
```

Error validasi (`422`):

```json
{
  "detail": [
    {"loc": ["body", "amount"], "msg": "Nominal tidak valid", "type": "value_error"}
  ]
}
```

---

## 6. Catatan untuk Agent

Panduan praktis saat Hermes memproses perintah pengguna:

1. **Selalu kirim header auth.** Tanpa itu semua endpoint (kecuali `/health`) -> `401`.

2. **Pakai nama dompet/kategori, bukan id**, supaya tidak perlu lookup dulu:

   ```json
   {"account": "BCA", "category": "Makanan"}
   ```

   API akan membuatnya kalau belum ada. Untuk menghindari typo membuat dompet baru, ambil dulu `GET /accounts` lalu pakai `account_id`.

3. **Tentukan `kind` dengan benar.** Salah `kind` = laporan keuangan salah:
   - uang keluar -> `expense`
   - uang masuk -> `income`
   - pindah antar dompet sendiri -> `transfer` (butuh `to_account`, bukan expense!)

4. **Jangan pakai `status: "pending"`** kecuali memang ingin transaksi belum masuk laporan. Default `confirmed` sudah benar.

5. **Nominal bisa langsung dari teks pengguna** (`"35rb"`, `"1,5jt"`) — API yang mem-parsing.

6. **Setelah menulis data, baca `/summary`** untuk mengonfirmasi saldo terbaru ke pengguna.

7. **Untuk koreksi, pakai `PATCH`** (bukan delete + create), supaya riwayat audit tetap rapi.

8. **Kalau `409` saat hapus dompet**, artinya masih ada transaksi aktif. Tanya pengguna apakah ingin dipindah atau dihapus (`?force=true`).

9. **Bulk input**: gunakan `/import/csv/text` daripada memanggil `POST /transactions` berkali-kali.

10. **Endpoint yang mengubah data**: `POST`, `PATCH`, `DELETE`. `GET` selalu aman diulang.

---

## 7. Referensi Cepat

| Method | Path | Fungsi |
|---|---|---|
| GET | `/api/v1/health` | Cek status (tanpa auth) |
| GET | `/api/v1/summary` | Total saldo + ringkasan dompet |
| GET | `/api/v1/transactions` | List transaksi |
| POST | `/api/v1/transactions` | Buat transaksi |
| GET | `/api/v1/transactions/{id}` | Detail transaksi |
| PATCH | `/api/v1/transactions/{id}` | Ubah transaksi |
| DELETE | `/api/v1/transactions/{id}` | Hapus transaksi |
| GET | `/api/v1/accounts` | List dompet + saldo |
| POST | `/api/v1/accounts` | Buat dompet |
| GET | `/api/v1/accounts/{id}` | Detail dompet |
| PATCH | `/api/v1/accounts/{id}` | Ubah dompet |
| DELETE | `/api/v1/accounts/{id}` | Hapus dompet |
| POST | `/api/v1/accounts/sync` | Hitung ulang saldo |
| GET | `/api/v1/categories` | List kategori |
| POST | `/api/v1/categories` | Buat kategori |
| PATCH | `/api/v1/categories/{id}` | Ubah kategori |
| DELETE | `/api/v1/categories/{id}` | Hapus kategori |
| GET | `/api/v1/budgets` | Progress budget |
| POST | `/api/v1/import/csv` | Import CSV (multipart) |
| POST | `/api/v1/import/csv/text` | Import CSV (JSON string) |
| GET | `/api/v1/export/transactions` | Export transaksi (JSON) |
