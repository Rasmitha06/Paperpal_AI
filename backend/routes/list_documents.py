from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.config import list_documents_for_user
from backend.deps import require_user
from backend.models.document import DocumentInfo

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/list_documents")
async def list_documents(user: dict = Depends(require_user)):
    try:
        docs = list_documents_for_user(user["id"])
        return {
            "documents": [DocumentInfo(**d) for d in docs],
        }
    except Exception as exc:
        raise HTTPException(500, f"List failed: {exc}") from exc
