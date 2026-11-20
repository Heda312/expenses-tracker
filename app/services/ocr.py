"""OCR engine wrapper using RapidOCR (ONNX).

Satu engine saja: RapidOCR. Preprocessing (upscale + CLAHE) dipakai sebagai
percobaan kedua kalau gambar mentah menghasilkan terlalu sedikit teks.
"""
import logging

logger = logging.getLogger(__name__)

_engine = None
_engine_error = None


class OcrError(RuntimeError):
    """Raised when image cannot be read or engine unavailable."""


def _get_engine():
    global _engine, _engine_error
    if _engine is None:
        if _engine_error is not None:
            raise OcrError(str(_engine_error))
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            _engine_error = (
                "rapidocr-onnxruntime belum siap. Pastikan VC++ Redistributable "
                "terpasang dan jalankan: pip install -r requirements.txt"
            )
            raise OcrError(str(_engine_error)) from exc
        try:
            logger.info("Memuat model RapidOCR...")
            _engine = RapidOCR()
            logger.info("Model RapidOCR siap.")
        except Exception as exc:
            _engine_error = f"RapidOCR tidak bisa dimuat: {exc}"
            raise OcrError(_engine_error) from exc
    return _engine


def _decode(image_bytes: bytes):
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise OcrError("Gambar tidak bisa dibaca.")
    return image


def _run_ocr(image):
    """Jalankan RapidOCR pada array gambar atau bytes mentah."""
    engine = _get_engine()
    try:
        if isinstance(image, bytes):
            image = _decode(image)
        result, _ = engine(image)
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f"OCR gagal: {exc}") from exc

    lines = []
    for item in result or []:
        try:
            box, text, score = item
        except (TypeError, ValueError):
            continue
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
        except Exception:  # noqa: BLE001 - box OCR rusak dilewati, bukan fatal
            logger.debug("Box OCR tidak valid, dilewati", exc_info=True)
            continue

    lines.sort(key=lambda line: (line["top"], line["left"]))
    return lines


def _preprocess(image_bytes: bytes):
    """Upscale gambar kecil + tingkatkan kontras lokal (CLAHE)."""
    import cv2

    image = _decode(image_bytes)

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
    return clahe.apply(gray)


def read_lines(image_bytes: bytes) -> list[dict]:
    """Baca gambar, kembalikan daftar baris teks beserta posisinya."""
    all_lines = []
    # Coba gambar mentah dulu (lebih toleran terhadap struk berwarna).
    try:
        all_lines = _run_ocr(image_bytes)
        if len(all_lines) >= 3:
            return all_lines
    except OcrError:
        raise
    except Exception:
        logger.debug("OCR gambar mentah gagal, coba preprocessing.", exc_info=True)

    # Percobaan kedua: gambar yang sudah dipertajam.
    try:
        all_lines = _run_ocr(_preprocess(image_bytes))
    except OcrError:
        raise
    except Exception:
        logger.debug("OCR dengan preprocessing gagal.", exc_info=True)

    if not all_lines:
        raise OcrError("Tidak ada teks yang terbaca dari gambar ini.")
    return all_lines