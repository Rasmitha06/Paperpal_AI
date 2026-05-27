from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    page_count: int
    chunk_count: int
    message: str


class RetrievedChunk(BaseModel):
    chunk_id: str
    page: int
    score: float
    text: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    doc_id: str
    chunk_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    retrieved_chunks: List[RetrievedChunk]
    relevancy_score: Optional[float] = None
    relevancy_passing: Optional[bool] = None


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    page_count: int
    chunk_count: int


class SummaryRequest(BaseModel):
    doc_id: str


class SummaryResponse(BaseModel):
    doc_id: str
    filename: str
    page_count: int
    answer: str
