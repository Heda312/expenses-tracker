"""OCR engine wrapper using EasyOCR.

EasyOCR lebih akurat daripada rapidocr-onnxruntime,
cocok buat baca struk Indonesia.
"""
import logging
import io

logger = logging.getLogger(__name__)

_engine = None


class OcrError(RuntimeError):
    """Raised when image cannot be read or engine unavailable."""


def _get_engine():
    global _engine
    if _engine is None:
        try:
            import easyocr
        except ImportError as exc:  # pragma: no cover
            raise OcrError(
                "easyocr belum terpasang. Jalankan: pip install easyocr"
            ) from exc
        logger.info("Memuat model EasyOCR...")
        _engine = easyocr.Reader(["id", "en"], gpu=False)
        logger.info("Model EasyOCR siap.")
    return _engine


def _run_ocr(image_bytes: bytes):
    engine = _get_engine()
    try:
        result = engine.readtext(image_bytes, detail=1, paragraph=False)
    except Exception as exc:
        raise OcrError(f"OCR gagal: {exc}") from exc

    lines = []
    for box, text, score in result or []:
        if not text or not str(text).strip():
            continue
        try:
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            lines.append(
                {
                    "text": str(text).strip(),
                    "top": float(min(ys)),
                    "left": float(min(xs)),
                    "height": float(max(ys) - min(ys)),
                    "score": float(score),
                }
            )
        except Exception:
            continue

    lines.sort(key=lambda line: (line["top"], line["left"]))
    return lines


def _preprocess(image_bytes: bytes):
    import cv2
    import numpy as np

    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise OcrError("Gambar tidak bisa dibaca.")

    h, w = image.shape[:2]
    max_side = max(h, w)
    if max_side < 1800:
        scale = 1800 / max_side
        image = cv2.resize(
            image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return gray


def read_lines(image_bytes: bytes) -> list[dict]:
    """Baca gambar, kembalikan daftar baris teks beserta posisinya."""
    all_lines = []
    # Try raw image first (more lenient)
    try:
        all_lines = _run_ocr(image_bytes)
        if len(all_lines) >= 3:
            return all_lines
    except Exception:
        pass

    try:
        img = _preprocess(image_bytes)
        all_lines = _run_ocr(img)
        if len(all_lines) >= 3:
            return all_lines
    except Exception:
        pass

    if not all_lines:
        raise OcrError("Tidak ada teks yang terbaca dari gambar ini.")
    return all_lines
