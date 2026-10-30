"""Pembungkus OCR (RapidOCR / PaddleOCR versi ONNX).

Engine dimuat malas (lazy) supaya aplikasi tetap bisa start walau
rapidocr belum terpasang. Kalau OCR gagal, pengguna masih bisa
mengisi transaksi manual.
"""

import logging

logger = logging.getLogger(__name__)

_engine = None


class OcrError(RuntimeError):
    """Dilempar kalau gambar tidak bisa dibaca atau engine tidak tersedia."""


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            raise OcrError(
                "rapidocr-onnxruntime belum terpasang. Jalankan: pip install -r requirements.txt"
            ) from exc
        logger.info("Memuat model OCR...")
        _engine = RapidOCR()
        logger.info("Model OCR siap.")
    return _engine


def _run_ocr(image):
    engine = _get_engine()
    try:
        result, _elapsed = engine(image)
    except Exception as exc:
        raise OcrError(f"OCR gagal: {exc}") from exc

    lines = []
    for box, text, score in result or []:
        if not text or not str(text).strip():
            continue
        try:
            ys = [point[1] for point in box]
            xs = [point[0] for point in box]
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


def _preprocess_gray(image_bytes: bytes):
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
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return gray


def _upscale_color(image_bytes: bytes):
    import cv2
    import numpy as np

    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise OcrError("Gambar tidak bisa dibaca.")

    h, w = image.shape[:2]
    max_side = max(h, w)
    if max_side < 2200:
        scale = 2200 / max_side
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    return image


def read_lines(image_bytes: bytes) -> list[dict]:
    """Baca gambar, kembalikan daftar baris teks beserta posisinya."""
    lines = []
    try:
        img = _preprocess_gray(image_bytes)
        lines = _run_ocr(img)
        if len(lines) >= 5:
            return lines
    except Exception:
        lines = []

    try:
        img = _upscale_color(image_bytes)
        lines2 = _run_ocr(img)
        if len(lines2) > len(lines):
            lines = lines2
    except Exception:
        pass

    if not lines:
        raise OcrError("Tidak ada teks yang terbaca dari gambar ini.")
    return lines
