from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

_easyocr_reader = None


def tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401

        return True
    except ImportError:
        return False


def ocr_available() -> bool:
    return tesseract_available() or easyocr_available()


def ocr_engine_name() -> str:
    if tesseract_available():
        return "tesseract"
    if easyocr_available():
        return "easyocr"
    return "none"


def ocr_setup_hint() -> str:
    if ocr_available():
        return f"OCR ready ({ocr_engine_name()})"
    return (
        "OCR not available. Choose one: "
        "(1) Install Homebrew: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\" "
        "then brew install tesseract — OR — "
        "(2) pip install easyocr  (no Homebrew needed, ~1GB download)"
    )


def _clean_ocr_text(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _ocr_tesseract(image_bytes: bytes, lang: str = "eng") -> str:
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(image, lang=lang) or ""


def _ocr_easyocr(image_bytes: bytes) -> str:
    global _easyocr_reader
    import easyocr
    import numpy as np
    from PIL import Image

    if _easyocr_reader is None:
        logger.info("Loading EasyOCR model (first run may take a minute)...")
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    img = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
    results = _easyocr_reader.readtext(img)
    return "\n".join(line[1] for line in results if line[1])


def ocr_image_bytes(image_bytes: bytes, lang: str = "eng") -> str:
    if tesseract_available():
        return _ocr_tesseract(image_bytes, lang=lang)
    if easyocr_available():
        return _ocr_easyocr(image_bytes)
    return ""


def ocr_pdf_page(pixmap_bytes: bytes, lang: str = "eng") -> str:
    return _clean_ocr_text(ocr_image_bytes(pixmap_bytes, lang=lang))


def render_page_for_ocr(page, scale: float = 2.0) -> bytes:
    """Render a PyMuPDF page to PNG bytes for OCR."""
    import fitz

    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return pix.tobytes("png")


def extract_tables_from_page(pdf_page) -> str:
    """Extract tables from a pdfplumber page as readable text."""
    tables = pdf_page.extract_tables() or []
    if not tables:
        return ""

    blocks: list[str] = []
    for idx, table in enumerate(tables, start=1):
        if not table:
            continue
        rows = []
        for row in table:
            cells = [str(c or "").strip().replace("\n", " ") for c in row]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            blocks.append(
                f"### Table {idx} (page {pdf_page.page_number})\n" + "\n".join(rows)
            )
    return "\n\n".join(blocks)
