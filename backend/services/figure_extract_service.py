from __future__ import annotations

import base64
import io
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

import fitz
import pdfplumber

from backend.config import UPLOAD_DIR, load_registry, settings
from backend.services.langchain_stack import retrieve_chunks
from backend.services.vision_service import (
    analyze_figure_crop,
    extract_figure_ids,
    page_likely_has_figures,
    vision_render_scale,
)

FIG_ID_NORM = re.compile(r"fig\.?\s*([\d.]+(?:\s*[\d.]+)*)", re.IGNORECASE)
MIN_CLIP_PX = 72


def resolve_pdf_path(doc_id: str) -> Path:
    direct = UPLOAD_DIR / doc_id
    if direct.exists():
        return direct
    for doc in load_registry():
        if doc.get("doc_id") == doc_id:
            path = UPLOAD_DIR / doc["filename"]
            if path.exists():
                return path
    raise ValueError(
        f"PDF not found for '{doc_id}'. Re-upload the file to enable figure extraction."
    )


CAPTION_LINE_RE = re.compile(
    r"(Figure\s*[\d.]+(?:\s*[\d.]+)*|Fig\.?\s*[\d.]+(?:\s*[\d.]+)*)"
    r"[:\s—–-]*([^\n]{0,220})",
    re.IGNORECASE,
)


def _parse_page_figure_captions(page_text: str) -> list[dict]:
    """Extract figure IDs and caption lines from page text."""
    captions: list[dict] = []
    seen: set[str] = set()
    for match in CAPTION_LINE_RE.finditer(page_text or ""):
        fig_id = _normalize_figure_id(match.group(1).strip())
        if fig_id in seen:
            continue
        seen.add(fig_id)
        desc = (match.group(2) or "").strip()
        desc = re.sub(r"\s+", " ", desc)
        captions.append({"figure_id": fig_id, "description": desc[:200]})
    return captions


def _figure_context_for_vision(hint: str, native: str) -> str:
    """Short caption-only context — never dump the whole page."""
    hint = (hint or "").strip()
    if hint and not hint.lower().startswith("embedded image"):
        return hint[:350]

    captions = _parse_page_figure_captions(native)
    if captions:
        lines = []
        for c in captions[:4]:
            line = c["figure_id"]
            if c["description"]:
                line += f": {c['description']}"
            lines.append(line)
        return "\n".join(lines)[:400]
    return f"Figure on page (see image)."


def _sanitize_title(title: str, figure_id: str, caption_desc: str = "") -> str:
    t = (title or "").strip()
    bad = (
        not t
        or "embedded image" in t.lower()
        or len(t) > 120
        or t.count("Fig") > 2
    )
    if bad:
        if caption_desc:
            return caption_desc[:100]
        return ""
    if t.lower().startswith(figure_id.lower()):
        t = t[len(figure_id) :].lstrip(": ").strip()
    return t[:100]


def _sanitize_introduction(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text.strip())
    if (
        "embedded image on page" in t.lower()
        or len(t) > 400
        or t.count("Fig.") > 2
    ):
        sentences = re.split(r"(?<=[.!?])\s+", t)
        t = " ".join(sentences[:2]).strip()
    return t[:320]


def _caption_desc_for_fig(fig_id: str, native: str) -> str:
    for c in _parse_page_figure_captions(native):
        if c["figure_id"] == fig_id or _normalize_figure_id(c["figure_id"]) == fig_id:
            return c["description"]
    return ""


def _normalize_figure_id(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "Figure"
    match = FIG_ID_NORM.search(raw)
    if match:
        num = match.group(1).strip()
        return f"Fig. {num}" if not raw.lower().startswith("figure") else raw
    if re.match(r"figure\s", raw, re.I):
        return raw
    return raw


def _parse_chart_lines(vision_text: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    in_data = False
    for line in (vision_text or "").splitlines():
        upper = line.upper()
        if "CHART_DATA" in upper:
            in_data = True
            if "none" in line.lower():
                return grouped
            continue
        if not in_data or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        fig_id = _normalize_figure_id(parts[0])
        grouped[fig_id].append(
            {
                "chart_type": parts[1],
                "color": parts[2],
                "category": parts[3],
                "value": parts[4],
            }
        )
    return grouped


def _cached_vision_for_page(doc_id: str, page_num: int) -> str:
    try:
        chart_chunks = retrieve_chunks(
            "CHART_DATA figure chart segments legend",
            doc_id,
            chunk_id=f"chart_p{page_num}",
            score_threshold=1.0,
            top_k=2,
        )
        if chart_chunks:
            return chart_chunks[0]["text"]

        body_chunks = retrieve_chunks(
            "Figure chart analysis vision visual description",
            doc_id,
            score_threshold=1.0,
            top_k=24,
        )
        for chunk in body_chunks:
            if chunk.get("page") == page_num and (
                "chart analysis" in chunk["text"].lower()
                or "chart_data" in chunk["text"].lower()
            ):
                return chunk["text"]
    except Exception:
        pass
    return ""


def _render_clip(page: fitz.Page, rect: fitz.Rect, scale: float) -> Optional[bytes]:
    clip = rect & page.rect
    if clip.is_empty or clip.width < MIN_CLIP_PX or clip.height < MIN_CLIP_PX:
        return None
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    return pix.tobytes("png")


def _embedded_image_clips(
    page: fitz.Page, doc: fitz.Document, scale: float
) -> list[tuple[bytes, str]]:
    """Extract cropped PNGs for each embedded image on the page."""
    clips: list[tuple[bytes, float, str]] = []
    try:
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            page_area = page.rect.width * page.rect.height
            for rect in rects:
                area = rect.width * rect.height
                if page_area > 0 and area < page_area * 0.02:
                    continue
                png = _render_clip(page, rect, scale)
                if not png:
                    continue
                page_caps = _parse_page_figure_captions(
                    page.get_text("text") or ""
                )
                if page_caps:
                    cap = page_caps[min(len(clips), len(page_caps) - 1)]
                    hint = f"{cap['figure_id']}: {cap['description']}".strip(": ")
                else:
                    hint = f"Figure on page {page.number + 1}"
                clips.append((png, area, hint))
    except Exception:
        pass

    clips.sort(key=lambda x: -x[1])
    seen_areas: list[float] = []
    out: list[tuple[bytes, str]] = []
    for png, area, hint in clips:
        if any(abs(area - a) / max(area, 1) < 0.05 for a in seen_areas):
            continue
        seen_areas.append(area)
        out.append((png, hint))
    return out[:4]


def _caption_anchor_clips(
    page: fitz.Page, page_text: str, scale: float
) -> list[tuple[bytes, str]]:
    """Crop the region above a Figure/Fig. caption line."""
    page_rect = page.rect
    hints: list[tuple[fitz.Rect, str]] = []

    for match in re.finditer(
        r"(Figure\s*[\d.]+(?:\s*[\d.]+)*|Fig\.?\s*[\d.]+(?:\s*[\d.]+)*)[:\s—–-]*(.*)",
        page_text,
        re.IGNORECASE,
    ):
        label = match.group(1).strip()
        title_hint = (match.group(2) or "").strip()[:120]
        for rect in page.search_for(label.split()[0] if " " in label else label):
            crop_h = min(450, page_rect.height * 0.62)
            crop = fitz.Rect(
                page_rect.x0 + 28,
                max(page_rect.y0 + 20, rect.y0 - crop_h),
                page_rect.x1 - 28,
                rect.y0 - 6,
            )
            hints.append((crop & page_rect, f"{label}: {title_hint}".strip(": ")))

    if not hints:
        for label in extract_figure_ids(page_text):
            for rect in page.search_for(label[:12]):
                crop_h = min(400, page_rect.height * 0.55)
                crop = fitz.Rect(
                    page_rect.x0 + 28,
                    max(page_rect.y0 + 20, rect.y0 - crop_h),
                    page_rect.x1 - 28,
                    rect.y0 - 6,
                )
                hints.append((crop & page_rect, label))

    out: list[tuple[bytes, str]] = []
    for crop, hint in hints:
        png = _render_clip(page, crop, scale)
        if png:
            out.append((png, hint))
    return out[:2]


def _segments_to_table(segments: list[dict]) -> tuple[list[str], list[list[str]]]:
    if not segments:
        return [], []
    headers = ["Category", "Percentage", "Color"]
    rows = [
        [s.get("category", ""), s.get("value", ""), s.get("color", "")]
        for s in segments
    ]
    return headers, rows


def _analysis_to_figure_dict(
    analysis,
    image_index: int,
    page_num: int,
    image_b64: str,
    segments: list[dict],
    chart_type: str,
) -> dict:
    headers = list(analysis.table_headers or [])
    rows = [list(r) for r in (analysis.table_rows or [])]
    if not rows and segments:
        headers, rows = _segments_to_table(segments)

    figure_id = _normalize_figure_id(analysis.figure_id or "Figure")
    title = _sanitize_title(analysis.title or "", figure_id)
    if not title:
        title = figure_id
    intro = _sanitize_introduction(analysis.introduction or "")
    label = f"Image {image_index} – {figure_id}: {title}"

    return {
        "image_index": image_index,
        "label": label,
        "figure_id": figure_id,
        "title": title,
        "page": page_num,
        "chart_type": chart_type or analysis.figure_type or "figure",
        "figure_type": analysis.figure_type or "other",
        "image_base64": image_b64,
        "introduction": intro,
        "table_headers": headers,
        "table_rows": rows,
        "bullet_points": list(analysis.bullet_points or []),
        "key_takeaway": analysis.key_takeaway or "",
        "purpose": analysis.purpose or "",
        "segments": segments,
    }


def _fallback_figure(
    image_index: int,
    page_num: int,
    image_b64: str,
    fig_id: str,
    segments: list[dict],
    context: str,
    native: str = "",
) -> dict:
    headers, rows = _segments_to_table(segments)
    fig_id = _normalize_figure_id(fig_id)
    caption_desc = _caption_desc_for_fig(fig_id, native)
    intro = _sanitize_introduction(caption_desc or context)
    if not intro or intro.lower().startswith("embedded"):
        intro = f"Figure shown on page {page_num}."
    takeaway = ""
    if segments:
        top = max(segments, key=lambda s: _pct_value(s.get("value", "0")))
        takeaway = (
            f"Largest segment: {top.get('category')} at {top.get('value')}."
        )
    title = _sanitize_title("", fig_id, caption_desc) or caption_desc[:80] or fig_id
    return {
        "image_index": image_index,
        "label": f"Image {image_index} – {fig_id}: {title}",
        "figure_id": fig_id,
        "title": title,
        "page": page_num,
        "chart_type": segments[0]["chart_type"] if segments else "figure",
        "figure_type": "chart" if segments else "other",
        "image_base64": image_b64,
        "introduction": intro,
        "table_headers": headers,
        "table_rows": rows,
        "bullet_points": [],
        "key_takeaway": takeaway,
        "segments": segments,
    }


def _pct_value(val: str) -> float:
    try:
        return float(str(val).replace("%", "").strip())
    except ValueError:
        return 0.0


def extract_charts_and_figures(doc_id: str) -> dict:
    """Isolated figure crops with structured summaries (tables + takeaways)."""
    pdf_path = resolve_pdf_path(doc_id)
    file_bytes = pdf_path.read_bytes()
    fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")

    figures: list[dict] = []
    image_index = 0

    try:
        plumber_doc = pdfplumber.open(io.BytesIO(file_bytes))
        try:
            for i in range(len(fitz_doc)):
                page_num = i + 1
                page = fitz_doc[i]
                native = (page.get_text("text") or "").strip()
                if not page_likely_has_figures(page, native):
                    continue

                scale = vision_render_scale(native)
                vision_text = _cached_vision_for_page(doc_id, page_num)
                grouped = _parse_chart_lines(vision_text)

                page_captions = _parse_page_figure_captions(native)
                clip_list = _caption_anchor_clips(page, native, scale)
                if not clip_list:
                    clip_list = _embedded_image_clips(page, fitz_doc, scale)

                if not clip_list:
                    continue

                seen_fig_ids: set[str] = set()
                for png_bytes, hint in clip_list:
                    vision_ctx = _figure_context_for_vision(hint, native)
                    analysis = analyze_figure_crop(
                        png_bytes, page_num, vision_ctx
                    )
                    fig_id = _normalize_figure_id(
                        (analysis.figure_id if analysis else None) or hint
                    )
                    if fig_id in seen_fig_ids:
                        continue
                    seen_fig_ids.add(fig_id)

                    image_index += 1
                    image_b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
                    caption_desc = _caption_desc_for_fig(fig_id, native)
                    segments = grouped.get(fig_id, [])
                    if not segments and grouped:
                        segments = next(iter(grouped.values()), [])

                    chart_type = (
                        segments[0]["chart_type"] if segments else "figure"
                    )

                    if analysis:
                        if not _sanitize_title(analysis.title, fig_id, caption_desc):
                            analysis.title = caption_desc or fig_id
                        if caption_desc and not _sanitize_introduction(
                            analysis.introduction or ""
                        ):
                            analysis.introduction = caption_desc
                        figures.append(
                            _analysis_to_figure_dict(
                                analysis,
                                image_index,
                                page_num,
                                image_b64,
                                segments,
                                chart_type,
                            )
                        )
                    else:
                        figures.append(
                            _fallback_figure(
                                image_index,
                                page_num,
                                image_b64,
                                fig_id,
                                segments,
                                vision_ctx,
                                native=native,
                            )
                        )
        finally:
            plumber_doc.close()
    finally:
        fitz_doc.close()

    if not figures:
        return {
            "figures": [],
            "message": (
                "No isolated figures found. Re-upload the PDF with vision enabled, "
                "or ensure figures are embedded images or have Figure captions."
            ),
        }
    return {"figures": figures, "count": len(figures)}
