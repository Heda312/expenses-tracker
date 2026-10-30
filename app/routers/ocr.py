"""OCR endpoint untuk upload struk."""

import asyncio
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from app.security import require_user
from app.services import ocr, receipt

router = APIRouter()


@router.post("/ocr")
async def ocr_endpoint(
    file: UploadFile = File(...),
    _user=Depends(require_user),
):
    """Parse receipt from uploaded image."""
    # Relax content-type check — some browsers send different formats
    ct = file.content_type or ""
    if not any(ct.startswith(t) for t in ("image/", "multipart/")):
        return JSONResponse({"error": "Invalid file type"}, status_code=400)

    content = await file.read()
    try:
        lines = await asyncio.to_thread(ocr.read_lines, content)
    except ocr.OcrError as exc:
        return JSONResponse({"error": f"OCR failed: {str(exc)}"}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Unexpected error: {str(exc)}"}, status_code=400)

    data = receipt.parse_receipt(lines)

    return JSONResponse({
        "amount": data.amount or 0,
        "merchant": data.merchant or "",
        "occurred_at": data.date.strftime("%Y-%m-%dT%H:%M") if data.date else "",
        "text": data.raw_text or "",
        "confidence": data.confidence or 0,
    })
