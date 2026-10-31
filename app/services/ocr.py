"""OCR engine wrapper using RapidOCR."""
import logging

logger = logging.getLogger(__name__)

_engine = None
_engine_error = None
_easy_engine = None


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


def _get_easy_engine():
    """Fallback OCR cross-platform memakai EasyOCR."""
    global _easy_engine
    if _easy_engine is None:
        try:
            import easyocr
            logger.info("Memuat model EasyOCR...")
            _easy_engine = easyocr.Reader(["id", "en"], gpu=False, verbose=False)
            logger.info("Model EasyOCR siap.")
        except Exception as exc:
            raise OcrError(f"EasyOCR tidak bisa dimuat: {exc}") from exc
    return _easy_engine


def _run_easyocr(image_bytes: bytes):
    """Jalankan EasyOCR tanpa dependency binary khusus OS."""
    try:
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise OcrError("Gambar tidak bisa dibaca.")
        result = _get_easy_engine().readtext(image, detail=1, paragraph=False)
        lines = []
        for box, text, score in result or []:
            text = str(text).strip()
            if text:
                xs = [point[0] for point in box]
                ys = [point[1] for point in box]
                lines.append({
                    "text": text,
                    "top": float(min(ys)),
                    "left": float(min(xs)),
                    "height": float(max(ys) - min(ys)),
                    "score": float(score),
                })
        return lines
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f"EasyOCR gagal: {exc}") from exc


def _run_ocr(image_bytes: bytes):
    engine = _get_engine()
    try:
        import cv2
        import numpy as np

        if isinstance(image_bytes, bytes):
            image = cv2.imdecode(
                np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if image is None:
                raise OcrError("Gambar tidak bisa dibaca.")
        else:
            image = image_bytes
        result, _ = engine(image)
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
        try:
            all_lines = _run_easyocr(image_bytes)
        except OcrError as exc:
            logger.warning("OCR fallback gagal: %s", exc)

    if not all_lines:
        raise OcrError("Tidak ada teks yang terbaca dari gambar ini.")
    return all_lines
