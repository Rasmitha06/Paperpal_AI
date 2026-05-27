from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.config import UPLOAD_DIR, link_document_owner
from backend.deps import record_operation, require_operation_slot
from backend.services.history_service import save_upload_history
from backend.models.document import UploadResponse
from backend.services.pdf_processor import extract_and_chunk
from backend.services.vector_store import VectorStore

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    identity: dict = Depends(require_operation_slot),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")

    try:
        processed = extract_and_chunk(file.filename, data)
        save_path = UPLOAD_DIR / file.filename
        save_path.write_bytes(data)

        store = VectorStore()
        chunk_count = store.upsert_document(
            doc_id=processed.doc_id,
            filename=processed.filename,
            page_count=processed.page_count,
            chunks=processed.chunks,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Upload failed: {exc}") from exc

    record_operation(identity)

    if identity["type"] == "user":
        link_document_owner(processed.doc_id, identity["user"]["id"])
        save_upload_history(
            identity,
            processed.doc_id,
            processed.filename,
            processed.page_count,
            chunk_count,
        )

    return UploadResponse(
        doc_id=processed.doc_id,
        filename=processed.filename,
        page_count=processed.page_count,
        chunk_count=chunk_count,
        message="File uploaded successfully",
    )
