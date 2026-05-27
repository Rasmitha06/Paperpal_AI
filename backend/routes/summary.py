from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.config import load_registry
from backend.deps import record_operation, require_operation_slot
from backend.models.document import SummaryRequest, SummaryResponse
from backend.services.document_summary_service import summarize_full_document
from backend.services.history_service import filename_for_doc, save_search_history
from backend.services.langchain_stack import NO_INFO

router = APIRouter(prefix="/api", tags=["summary"])


def _page_count(doc_id: str) -> int:
    for doc in load_registry():
        if doc.get("doc_id") == doc_id:
            return int(doc.get("page_count") or 0)
    return 0


@router.post("/summary", response_model=SummaryResponse)
async def summarize_document(
    body: SummaryRequest,
    identity: dict = Depends(require_operation_slot),
):
    try:
        answer = summarize_full_document(body.doc_id)
        filename = filename_for_doc(body.doc_id)
        page_count = _page_count(body.doc_id)

        record_operation(identity)

        if not answer or answer == NO_INFO:
            raise HTTPException(
                404,
                "Could not summarize this PDF. Re-upload the file and try again.",
            )

        if identity["type"] == "user":
            save_search_history(
                identity,
                body.doc_id,
                filename,
                "Document summary (all pages)",
                answer,
                None,
                [],
            )

        return SummaryResponse(
            doc_id=body.doc_id,
            filename=filename,
            page_count=page_count,
            answer=answer,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Summary failed: {exc}") from exc
