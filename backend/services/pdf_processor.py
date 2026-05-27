from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pdfplumber
from langchain_core.documents import Document

from backend.config import settings
from backend.services.langchain_stack import get_text_splitter
from backend.services.ocr_service import (
    extract_tables_from_page,
    ocr_available,
    ocr_pdf_page,
    ocr_setup_hint,
    render_page_for_ocr,
)
from backend.services.vision_service import (
    describe_page_visuals,
    extract_figure_ids,
    page_likely_has_figures,
    vision_render_scale,
)


@dataclass
class ProcessedDocument:
    doc_id: str
    filename: str
    page_count: int
    chunks: list[dict]
    ocr_pages: int = 0
    table_pages: int = 0
    vision_pages: int = 0
    chart_chunks: int = 0
    extraction_notes: list[str] = field(default_factory=list)


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\f", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(Page\s+\d+\s+of\s+\d+)", "", text, flags=re.IGNORECASE)
    return text.strip()


def _extract_page_content(
    fitz_page,
    plumber_page,
    page_num: int,
    stats: dict,
) -> tuple[str, str]:
    """Returns (page_body_text, dedicated_chart_chunk_text)."""
    parts: list[str] = []
    chart_chunk = ""

    native = _clean_text(fitz_page.get_text("text") or "")
    if native:
        parts.append(native)

    if plumber_page is not None:
        tables = extract_tables_from_page(plumber_page)
        if tables:
            parts.append(tables)
            stats["table_pages"] += 1

    combined = "\n\n".join(parts).strip()
    needs_ocr = (
        settings.ocr_enabled
        and ocr_available()
        and len(combined) < settings.ocr_min_text_chars
    )

    if needs_ocr:
        try:
            png_bytes = render_page_for_ocr(fitz_page)
            ocr_text = _clean_text(ocr_pdf_page(png_bytes, lang=settings.ocr_lang))
            if ocr_text:
                parts.append(f"### OCR text (page {page_num})\n{ocr_text}")
                stats["ocr_pages"] += 1
        except Exception as exc:
            stats["notes"].append(f"OCR skipped on page {page_num}: {exc}")

    combined = "\n\n".join(parts).strip()
    if settings.vision_enabled and settings.openai_api_key:
        if page_likely_has_figures(fitz_page, combined):
            try:
                fig_hints = ", ".join(extract_figure_ids(combined)) or combined[:400]
                scale = vision_render_scale(combined)
                png_bytes = render_page_for_ocr(fitz_page, scale=scale)
                vision_full, chart_block = describe_page_visuals(
                    png_bytes, page_num, caption_hint=fig_hints
                )
                if vision_full:
                    parts.append(vision_full)
                    stats["vision_pages"] += 1
                if chart_block:
                    chart_chunk = chart_block
                    stats["chart_chunks"] += 1
            except Exception as exc:
                stats["notes"].append(f"Vision skipped on page {page_num}: {exc}")

    return "\n\n".join(parts).strip(), chart_chunk


def extract_and_chunk(filename: str, file_bytes: bytes) -> ProcessedDocument:
    stats = {
        "ocr_pages": 0,
        "table_pages": 0,
        "vision_pages": 0,
        "chart_chunks": 0,
        "notes": [],
    }

    if settings.ocr_enabled and not ocr_available():
        stats["notes"].append(ocr_setup_hint())

    fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
    plumber_doc = pdfplumber.open(io.BytesIO(file_bytes))

    pages: list[tuple[int, str, str]] = []
    try:
        for i in range(len(fitz_doc)):
            page_num = i + 1
            fitz_page = fitz_doc[i]
            plumber_page = plumber_doc.pages[i] if i < len(plumber_doc.pages) else None
            body, chart_block = _extract_page_content(
                fitz_page, plumber_page, page_num, stats
            )
            if body or chart_block:
                pages.append((page_num, body, chart_block))
    finally:
        fitz_doc.close()
        plumber_doc.close()

    if not pages:
        raise ValueError(
            "No readable text found. Install Tesseract for scanned PDFs or enable vision."
        )

    splitter = get_text_splitter()
    chunks: list[dict] = []
    chunk_index = 0

    for page_num, body, chart_block in pages:
        if chart_block:
            chunks.append(
                {
                    "chunk_id": f"chart_p{page_num}",
                    "page": page_num,
                    "text": chart_block,
                    "content_type": "chart",
                }
            )
            chunk_index += 1

        if body:
            lc_docs = [
                Document(page_content=body, metadata={"page": page_num}),
            ]
            for doc in splitter.split_documents(lc_docs):
                chunks.append(
                    {
                        "chunk_id": f"chunk_{chunk_index}",
                        "page": page_num,
                        "text": doc.page_content,
                        "content_type": "text",
                    }
                )
                chunk_index += 1

    if not chunks:
        raise ValueError("Could not create chunks from PDF text.")

    return ProcessedDocument(
        doc_id=filename,
        filename=filename,
        page_count=len(pages),
        chunks=chunks,
        ocr_pages=stats["ocr_pages"],
        table_pages=stats["table_pages"],
        vision_pages=stats["vision_pages"],
        chart_chunks=stats["chart_chunks"],
        extraction_notes=stats["notes"],
    )
