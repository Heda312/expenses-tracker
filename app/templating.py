"""Konfigurasi Jinja2 dan helper yang dipakai semua template."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import settings
from app.services.dates import (
    MONTH_LABELS,
    current_period,
    format_date,
    format_dt,
    now_local,
    period_label,
)
from app.services.money import format_idr, format_idr_compact

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Pesan singkat yang dikirim lewat query string ?flash=...
FLASH_MESSAGES = {
    "saved": ("ok", "Data tersimpan."),
    "updated": ("ok", "Perubahan disimpan."),
    "deleted": ("ok", "Data dihapus."),
    "archived": ("ok", "Dompet diarsipkan."),
    "restored": ("ok", "Dompet diaktifkan kembali."),
    "password": ("ok", "Password diganti. Silakan login ulang."),
    "invalid": ("err", "Data tidak valid. Periksa kembali isian Anda."),
    "notfound": ("err", "Data tidak ditemukan."),
    "no-select": ("err", "Pilih minimal satu transaksi."),
    "wrong": ("err", "Email atau password salah."),
    "locked": ("err", "Terlalu banyak percobaan. Coba lagi beberapa menit lagi."),
    "invalidlink": ("err", "Tautan tidak valid."),
}

templates.env.globals.update(
    app_name=settings.app_name,
    format_idr=format_idr,
    format_idr_compact=format_idr_compact,
    format_dt=format_dt,
    format_date=format_date,
    period_label=period_label,
    current_period=current_period,
    now_local=now_local,
    month_labels=MONTH_LABELS,
    flash_messages=FLASH_MESSAGES,
)
