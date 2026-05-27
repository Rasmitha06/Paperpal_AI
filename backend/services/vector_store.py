from __future__ import annotations

from typing import Optional

from backend.services.langchain_stack import (
    ingest_chunks,
    list_documents as list_indexed_documents,
    retrieve_chunks,
)


class VectorStore:
    """Pinecone vector store via LangChain PineconeVectorStore."""

    def upsert_document(
        self,
        doc_id: str,
        filename: str,
        page_count: int,
        chunks: list[dict],
    ) -> int:
        return ingest_chunks(doc_id, filename, page_count, chunks)

    def query(
        self,
        question: str,
        doc_id: str,
        chunk_id: Optional[str] = None,
        score_threshold: Optional[float] = None,
    ) -> list[dict]:
        return retrieve_chunks(question, doc_id, chunk_id, score_threshold)

    def list_documents(self) -> list[dict]:
        return list_indexed_documents()
