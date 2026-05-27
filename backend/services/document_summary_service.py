from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import fitz
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.config import UPLOAD_DIR, load_registry, settings
from backend.services.langchain_stack import NO_INFO

PAGE_BATCH_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Summarize PDF pages concisely for a merge step. 2–4 bullets per page.
Include headings, tools, links, lists. No invented content.""",
        ),
        (
            "human",
            """{filename} — pages {page_range} of {total_pages}

{page_text}

Markdown: ### Page N with bullets for each page in this batch.""",
        ),
    ]
)

MERGE_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Merge section notes into one document summary. All {total_pages} pages must appear in Full Summary.""",
        ),
        (
            "human",
            """{filename} ({total_pages} pages)

{section_notes}

## Brief Summary
(4–6 sentences)

## Full Summary
(### Page N or ### Pages 1–2; cover pages 1–{total_pages})

## Sources Used
- Pages 1–{total_pages}""",
        ),
    ]
)

ONE_SHOT_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Summarize the full PDF from the page text. Cover every page. No invented facts.""",
        ),
        (
            "human",
            """{filename} ({total_pages} pages)

{page_text}

## Brief Summary
## Full Summary
(### Page N for each page 1–{total_pages})
## Sources Used""",
        ),
    ]
)


def _get_summary_llm(*, merge: bool = False) -> ChatOpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required.")
    if merge and settings.summary_merge_model:
        model = settings.summary_merge_model
    else:
        model = settings.summary_model or settings.vision_model or "gpt-4o-mini"
    return ChatOpenAI(
        model=model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


def _load_pdf_pages(doc_id: str) -> List[dict]:
    path = UPLOAD_DIR / doc_id
    if not path.is_file():
        return []

    cap = settings.summary_max_page_chars
    doc = fitz.open(path)
    pages: List[dict] = []
    try:
        for i in range(len(doc)):
            page_num = i + 1
            text = (doc[i].get_text("text") or "").strip()
            if len(text) > cap:
                text = text[:cap] + "\n[…truncated…]"
            pages.append(
                {
                    "page": page_num,
                    "text": text or f"[Page {page_num}: no extractable text]",
                }
            )
    finally:
        doc.close()
    return pages


def _format_pages_for_prompt(pages: List[dict]) -> str:
    blocks = []
    for p in pages:
        blocks.append(f"--- Page {p['page']} ---\n{p['text']}")
    return "\n\n".join(blocks)


def _page_range_label(pages: List[dict]) -> str:
    nums = [p["page"] for p in pages]
    if len(nums) == 1:
        return str(nums[0])
    return f"{nums[0]}–{nums[-1]}"


def _batch_pages(pages: List[dict]) -> List[List[dict]]:
    per_batch = settings.summary_pages_per_batch
    max_chars = settings.summary_max_batch_chars
    batches: List[List[dict]] = []
    current: List[dict] = []
    char_count = 0

    for page in pages:
        page_len = len(page["text"])
        if current and (
            len(current) >= per_batch
            or (char_count + page_len > max_chars and len(current) >= 1)
        ):
            batches.append(current)
            current = []
            char_count = 0
        current.append(page)
        char_count += page_len

    if current:
        batches.append(current)
    return batches


def _summarize_page_batch(
    filename: str,
    batch: List[dict],
    total_pages: int,
) -> str:
    chain = PAGE_BATCH_PROMPT | _get_summary_llm(merge=False) | StrOutputParser()
    return chain.invoke(
        {
            "filename": filename,
            "page_range": _page_range_label(batch),
            "total_pages": total_pages,
            "page_text": _format_pages_for_prompt(batch),
        }
    ).strip()


def _summarize_batches_parallel(
    filename: str,
    batches: List[List[dict]],
    total_pages: int,
) -> List[str]:
    workers = min(settings.summary_max_workers, len(batches))
    if workers <= 1:
        return [
            _summarize_page_batch(filename, batch, total_pages) for batch in batches
        ]

    notes: List[str] = [""] * len(batches)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_summarize_page_batch, filename, batch, total_pages): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            idx = futures[future]
            notes[idx] = future.result()
    return [n for n in notes if n]


def _merge_section_summaries(
    filename: str,
    section_notes: List[str],
    total_pages: int,
) -> str:
    chain = MERGE_SUMMARY_PROMPT | _get_summary_llm(merge=True) | StrOutputParser()
    return chain.invoke(
        {
            "filename": filename,
            "total_pages": total_pages,
            "section_notes": "\n\n---\n\n".join(section_notes),
        }
    ).strip()


def _one_shot_summary(filename: str, pages: List[dict]) -> str:
    total = len(pages)
    chain = ONE_SHOT_SUMMARY_PROMPT | _get_summary_llm(merge=True) | StrOutputParser()
    return chain.invoke(
        {
            "filename": filename,
            "total_pages": total,
            "page_text": _format_pages_for_prompt(pages),
        }
    ).strip()


def summarize_full_document(doc_id: str) -> str:
    """
    Full-document summary: one fast LLM call when the PDF fits in context,
    otherwise parallel batch summarization + a single merge call.
    """
    pages = _load_pdf_pages(doc_id)
    if not pages:
        from backend.services.langchain_stack import (
            generate_summary_answer,
            retrieve_summary_chunks,
        )

        chunks = retrieve_summary_chunks(doc_id, "full document summary")
        if chunks:
            return generate_summary_answer(
                "Provide a brief and full summary of the entire document.",
                chunks,
            )
        return NO_INFO

    filename = doc_id
    for doc in load_registry():
        if doc.get("doc_id") == doc_id:
            filename = doc.get("filename") or doc_id
            break

    total_pages = len(pages)
    total_chars = sum(len(p["text"]) for p in pages)

    if (
        total_pages <= settings.summary_one_shot_max_pages
        and total_chars <= settings.summary_one_shot_max_chars
    ):
        result = _one_shot_summary(filename, pages)
        return result or NO_INFO

    batches = _batch_pages(pages)
    section_notes = _summarize_batches_parallel(filename, batches, total_pages)

    if not section_notes:
        return NO_INFO

    if len(section_notes) == 1:
        return _merge_section_summaries(filename, section_notes, total_pages) or section_notes[0]

    result = _merge_section_summaries(filename, section_notes, total_pages)
    return result or NO_INFO
