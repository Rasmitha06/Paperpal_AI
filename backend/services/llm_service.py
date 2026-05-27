from __future__ import annotations

from backend.services.langchain_stack import (
    NO_INFO,
    generate_answer,
    generate_summary_answer,
)


class LLMService:
    """Grounded Q&A via LangChain ChatPromptTemplate + ChatOpenAI LCEL chain."""

    def generate_answer(self, question: str, chunks: list[dict]) -> str:
        if not chunks:
            return NO_INFO
        return generate_answer(question, chunks)

    def generate_summary_answer(self, question: str, chunks: list[dict]) -> str:
        if not chunks:
            return NO_INFO
        return generate_summary_answer(question, chunks)
