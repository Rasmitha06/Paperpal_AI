from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.models.history import (
    ChatSessionResponse,
    ChatSessionSaveRequest,
    HistoryItem,
    HistoryListResponse,
)
from backend.services.history_service import (
    delete_history_item,
    get_chat_session,
    list_history_merged,
    resolve_owner_key,
    resolve_owner_keys,
    save_chat_session,
)

router = APIRouter(prefix="/api", tags=["history"])


def _require_owner(
    authorization: Optional[str] = Header(None),
    x_guest_id: Optional[str] = Header(None),
) -> str:
    owner = resolve_owner_key(authorization, x_guest_id)
    if not owner:
        raise HTTPException(401, "Sign in to view history.")
    return owner


@router.get("/history", response_model=HistoryListResponse)
async def get_history(
    kind: str = "all",
    limit: int = 40,
    authorization: Optional[str] = Header(None),
    x_guest_id: Optional[str] = Header(None),
):
    allowed = {"all", "search", "chat", "upload"}
    if kind not in allowed:
        raise HTTPException(400, f"kind must be one of: {', '.join(sorted(allowed))}")
    owner_keys = resolve_owner_keys(authorization, x_guest_id)
    if not owner_keys:
        raise HTTPException(401, "Sign in to view history.")
    items = list_history_merged(owner_keys, kind=kind, limit=limit)
    return HistoryListResponse(
        kind=kind,
        items=[HistoryItem(**i) for i in items],
    )


@router.get("/history/chat/{doc_id}", response_model=ChatSessionResponse)
async def get_chat(
    doc_id: str,
    owner_key: str = Depends(_require_owner),
):
    session = get_chat_session(owner_key, doc_id)
    if not session:
        return ChatSessionResponse(doc_id=doc_id, messages=[])
    return ChatSessionResponse(**session)


@router.put("/history/chat", response_model=ChatSessionResponse)
async def put_chat(
    body: ChatSessionSaveRequest,
    owner_key: str = Depends(_require_owner),
):
    save_chat_session(owner_key, body.doc_id, body.filename, body.messages)
    session = get_chat_session(owner_key, body.doc_id)
    if session:
        return ChatSessionResponse(**session)
    return ChatSessionResponse(doc_id=body.doc_id, filename=body.filename, messages=body.messages)


@router.delete("/history/{item_id}")
async def remove_history(
    item_id: int,
    kind: str = "search",
    owner_key: str = Depends(_require_owner),
):
    if not delete_history_item(owner_key, item_id, kind=kind):
        raise HTTPException(404, "History item not found.")
    return {"ok": True}
