from __future__ import annotations

import base64
import json
import logging
import re
from typing import List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from backend.config import settings

logger = logging.getLogger(__name__)

FIGURE_PATTERN = re.compile(
    r"\b(fig\.?\s*[\d.]+\s*[\d.]*|figure\s*[\d.]+|chart|graph|diagram|pie\s*chart)\b",
    re.IGNORECASE,
)
FIG_ID_PATTERN = re.compile(r"fig\.?\s*([\d.]+(?:\s*[\d.]+)*)", re.IGNORECASE)
FIGURE_NUM_PATTERN = re.compile(
    r"(figure\s*[\d.]+(?:\s*[\d.]+)*|fig\.?\s*[\d.]+(?:\s*[\d.]+)*)",
    re.IGNORECASE,
)

VISION_PROMPT = """You analyze PDF page images for charts, graphs, pie charts, and figures.

Output TWO sections exactly:

## Visual description
Brief description of what is shown.

## CHART_DATA (machine-readable — required if any chart exists)
For each chart, use this exact line format (one segment per line):
FIGURE_ID | CHART_TYPE | COLOR | CATEGORY_LABEL | PERCENTAGE_OR_VALUE

Example lines:
Fig. 4.4.1 | pie | red | 18-25 | 47.1%
Fig. 4.4.1 | pie | green | 35+ | 23.5%
Fig. 4.4.1 | pie | orange | 26-35 | 23.5%
Fig. 4.4.1 | pie | blue | Under 18 | 5.9%

Rules:
- Map every colored segment to its legend label and exact percentage shown on the chart.
- Use colors as written in the legend (red, green, orange, blue, etc.).
- If a percentage is printed on a slice, use that exact number.
- If no chart exists, write: CHART_DATA: none
- Do not guess values not visible."""


class FigureAnalysis(BaseModel):
    figure_id: str = Field(description="e.g. Fig. 4.4.1 or Figure 2.3.5")
    title: str = Field(
        description="Descriptive subtitle after figure ID, e.g. 'Schedule view showing shift details and staff on duty' or 'Age of Participants pie chart'",
    )
    figure_type: str = Field(
        default="other",
        description="chart | screenshot | diagram | table | photo | other",
    )
    introduction: str = Field(
        default="",
        description="1-2 sentences describing the figure",
    )
    table_headers: List[str] = Field(default_factory=list)
    table_rows: List[List[str]] = Field(default_factory=list)
    bullet_points: List[str] = Field(default_factory=list)
    key_takeaway: str = Field(
        default="",
        description="For charts: one-sentence data insight. For screenshots: leave empty if using purpose.",
    )
    purpose: str = Field(
        default="",
        description="For UI screenshots: what the figure is for (planning, workflow, etc.)",
    )


FIGURE_ANALYSIS_PROMPT = """Analyze ONLY the cropped figure image shown.

Caption hints from the PDF (use for figure_id and title only — do NOT copy this text into introduction):
{context}

Output rules:
- figure_id: e.g. "Fig. 4.6.2" from caption if present, else "Figure"
- title: short specific phrase (5–12 words) describing what THIS image shows. Never use "embedded image on page".
- introduction: exactly 1–2 sentences about what is visible IN THE IMAGE only. Max 280 characters. No section numbers, no unrelated paragraphs.
- figure_type: chart | screenshot | diagram | table | photo | other
- Charts: table_headers + table_rows from visible data only
- Screenshots: bullet_points as "Label: value"; purpose = one sentence; key_takeaway empty
- Charts: key_takeaway = one insight sentence from visible data
- Do not invent numbers. Do not paste page body text.
"""


def extract_figure_ids(page_text: str) -> list[str]:
    return [m.group(0) for m in FIG_ID_PATTERN.finditer(page_text or "")]


def page_likely_has_figures(fitz_page, page_text: str) -> bool:
    if FIGURE_PATTERN.search(page_text or ""):
        return True
    try:
        return len(fitz_page.get_images(full=True)) > 0
    except Exception:
        return False


def vision_render_scale(page_text: str) -> float:
    """Higher resolution for pages with figure references."""
    if FIGURE_PATTERN.search(page_text or ""):
        return 3.5
    return 2.5


def describe_page_visuals(
    png_bytes: bytes,
    page_num: int,
    caption_hint: str = "",
) -> tuple[str, str]:
    """
    Returns (full_vision_text, chart_only_block for dedicated indexing).
    """
    if not settings.openai_api_key:
        return "", ""

    client = OpenAI(api_key=settings.openai_api_key)
    b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
    hint = f"\nCaption/text on page: {caption_hint}" if caption_hint else ""

    try:
        response = client.chat.completions.create(
            model=settings.vision_model,
            temperature=0,
            max_tokens=1200,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT + hint},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return "", ""

        full = f"### Figure & chart analysis (page {page_num}, vision)\n{text}"
        chart_block = _extract_chart_block(text, page_num)
        return full, chart_block
    except Exception as exc:
        logger.warning("Vision analysis failed on page %s: %s", page_num, exc)
        return "", ""


def analyze_figure_crop(
    png_bytes: bytes,
    page_num: int,
    context: str = "",
) -> Optional[FigureAnalysis]:
    """Structured report for one isolated figure image."""
    if not settings.openai_api_key:
        return None

    client = OpenAI(api_key=settings.openai_api_key)
    b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
    prompt = FIGURE_ANALYSIS_PROMPT.format(context=(context or "(none)")[:2000])

    try:
        response = client.chat.completions.create(
            model=settings.vision_model,
            temperature=0,
            max_tokens=1400,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            return None
        data = json.loads(raw)
        return FigureAnalysis(**data)
    except Exception as exc:
        logger.warning(
            "Figure analysis failed on page %s: %s", page_num, exc
        )
        return None


def _extract_chart_block(vision_text: str, page_num: int) -> str:
    if "CHART_DATA" not in vision_text.upper():
        return ""
    lines = []
    in_data = False
    for line in vision_text.splitlines():
        upper = line.upper()
        if "CHART_DATA" in upper:
            in_data = True
            if "none" in line.lower():
                return ""
            continue
        if in_data and "|" in line:
            lines.append(line.strip())
    if not lines:
        return ""
    header = f"CHART_DATA page {page_num} searchable index:\n"
    return header + "\n".join(lines)
