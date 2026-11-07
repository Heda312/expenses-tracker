"""Format export CSV transaksi (round-trip).

Desain:
- Export HANYA berisi transaksi. Tidak ada export/import dompet terpisah.
- Dompet dibuat otomatis saat import, berdasarkan nama dompet yang muncul di
  transaksi.
- Jenis dompet (tunai / bank / e-wallet) ikut ditulis di kolom "Jenis Dompet"
  supaya tidak hilang. Kalau kolom itu kosong, jenis ditebak dari nama dompet
  (lihat wallet.guess_kind).
- Tanggal dan jam ditulis di kolom terpisah ("Tanggal" + "Waktu") dan
  dibaca kembali oleh importer, supaya jam transaksi tidak hilang.
"""

from __future__ import annotations

import csv
from io import StringIO

KIND_LABEL = {
    "expense": "Pengeluaran",
    "income": "Pemasukan",
    "transfer": "Transfer",
}

# Urutan kolom: kolom yang dikenali importer lebih dulu, lalu kolom informasi.
TRANSACTION_HEADERS = [
    "Tanggal",
    "Waktu",
    "Jenis",
    "Nominal",
    "Kategori",
    "Merchant",
    "Dompet",
    "Jenis Dompet",
    "Dompet Tujuan",
    "Catatan",
    "Status",
    "Sumber",
    "Reference ID",
]


def _clean(value) -> str:
    """Siapkan teks untuk CSV.

    Hanya karakter pembuka formula yang benar-benar berbahaya yang di-escape.
    Tanda "-" sengaja tidak ikut karena sering dipakai sebagai teks biasa
    (mis. "-" untuk data kosong) dan akan merusak round-trip import.
    """
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "@")):
        text = "'" + text
    return text


def build_transaction_csv(rows: list[dict]) -> StringIO:
    """CSV transaksi yang kompatibel dengan importer (termasuk jam)."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(TRANSACTION_HEADERS)

    for row in rows:
        writer.writerow(
            [
                row.get("date", ""),
                row.get("time", ""),
                KIND_LABEL.get(row.get("kind", ""), row.get("kind", "")),
                row.get("amount", 0),
                _clean(row.get("category")),
                _clean(row.get("merchant")),
                _clean(row.get("account")),
                _clean(row.get("account_kind")),
                _clean(row.get("to_account")),
                _clean(row.get("note")),
                row.get("status", "confirmed"),
                row.get("source", ""),
                row.get("id", ""),
            ]
        )

    output.seek(0)
    return output
