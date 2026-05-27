from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

HistoryKindFilter = Literal["all", "search", "chat", "upload"]


class HistoryItem(BaseModel):
    id: int
    kind: str
    doc_id: Optional[str] = None
    title: str
    payload: dict
    created_at: str


class HistoryListResponse(BaseModel):
    items: List[HistoryItem]
    kind: str


class ChatSessionSaveRequest(BaseModel):
    doc_id: str
    filename: str = ""
    messages: List[dict] = Field(default_factory=list)


class ChatSessionResponse(BaseModel):
    doc_id: str
    filename: str = ""
    messages: List[dict] = Field(default_factory=list)
    updated_at: Optional[str] = None
