from __future__ import annotations

from backend.services.langchain_stack import get_embeddings


class EmbeddingService:
    """Thin wrapper around LangChain OpenAIEmbeddings."""

    def __init__(self) -> None:
        self._embeddings = get_embeddings()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)
