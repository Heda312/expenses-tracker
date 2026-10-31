"""OCR endpoint untuk upload struk."""

import asyncio
import re
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.db import get_db
from app.models import Account
from app.security import require_user
from app.services import classify, ocr, receipt
from app.services.dates import now_local, parse_time
from sqlalchemy.orm import Session

router = APIRouter()

ACCOUNT_ALIASES = {
    "bca": ("bca", "bank central asia"),
    "mandiri": ("mandiri",),
    "bri": ("bri", "bank rakyat indonesia"),
    "bni": ("bni",),
    "btn": ("btn",),
    "qris": ("qris", "quick response code indonesian standard"),
    "gopay": ("gopay", "go pay", "gojek"),
    "dana": ("dana",),
    "ovo": ("ovo",),
    "shopeepay": ("shopeepay", "shopee pay", "shopee"),
    "linkaja": ("linkaja", "link aja"),
}


def _pick_account(accounts, raw_text: str):
    """Pilih dompet dengan skor kecocokan OCR tertinggi."""
    text = re.sub(r"[^a-z0-9]+", " ", raw_text.lower())
    best = accounts[0] if accounts else None
    best_score = 0
    for account in accounts:
        name = re.sub(r"[^a-z0-9]+", " ", account.name.lower()).strip()
        score = 0
        if name and re.search(rf"\b{re.escape(name)}\b", text):
            score = 100 + len(name)
        for key, aliases in ACCOUNT_ALIASES.items():
            if key in name or any(alias in name for alias in aliases):
                for alias in aliases:
                    if re.search(rf"\b{re.escape(alias)}\b", text):
                        score = max(score, 80 + len(alias))
        if score > best_score:
            best, best_score = account, score
    return best


def _compact_image(content: bytes) -> bytes:
    """Resize receipt agar OCR lebih cepat, tanpa merusak teks kecil."""
    try:
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return content
        height, width = image.shape[:2]
        max_side = 1800
        scale = min(1.0, max_side / max(height, width))
        if scale < 1:
            image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return encoded.tobytes() if ok else content
    except Exception:
        return content


@router.post("/ocr")
async def ocr_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
):
    """Parse receipt from uploaded image."""
    # Relax content-type check — some browsers send different formats
    ct = file.content_type or ""
    if not any(ct.startswith(t) for t in ("image/", "multipart/")):
        return JSONResponse({"error": "Invalid file type"}, status_code=400)

    content = await file.read()
    
    if len(content) == 0:
        return JSONResponse({"error": "File kosong"}, status_code=400)
    
    ocr_content = await asyncio.to_thread(_compact_image, content)
    try:
        lines = await asyncio.to_thread(ocr.read_lines, ocr_content)
    except ocr.OcrError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Unexpected error: {str(exc)}"}, status_code=400)

    data = receipt.parse_receipt(lines)
    raw_text = data.raw_text or ""
    income = re.search(r"\b(gaji|bonus|thr|insentif|refund|pemasukan|masuk|salary|payroll)\b", raw_text, re.I)
    accounts = list(db.scalars(select(Account).where(Account.archived.is_(False)).order_by(Account.id)).all())
    account = _pick_account(accounts, raw_text)
    kind = "income" if income else "expense"
    category_id, _category_source = await classify.classify_category(
        db, data.merchant, raw_text, use_llm=False, kind=kind
    )

    parsed_time = parse_time(raw_text)
    occurred_at = ""
    if data.date:
        # Struk memakai waktu lokal Asia/Jakarta. Endpoint mengisi input HTML
        # datetime-local, jadi kirim waktu lokal; konversi UTC hanya dilakukan
        # TransactionInput saat transaksi disimpan.
        from datetime import datetime, time

        local_time = parsed_time or now_local().time().replace(second=0, microsecond=0)
        occurred_at = datetime.combine(data.date, local_time).strftime("%Y-%m-%dT%H:%M")
    return JSONResponse({
        "amount": data.amount or 0,
        "kind": kind,
        "account_id": account.id if account else None,
        "category_id": category_id,
        "merchant": data.merchant or "",
        "occurred_at": occurred_at,
        "text": raw_text,
        "confidence": data.confidence or 0,
    })
