from __future__ import annotations

from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.config import settings

EVAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You evaluate if an answer is supported by retrieved context. "
            'Reply JSON only: {"score": 0.0-1.0, "passing": true/false}',
        ),
        (
            "human",
            "QUESTION: {question}\n\nANSWER: {answer}\n\nCONTEXT:\n{context}",
        ),
    ]
)


class EvaluationService:
    """LangChain prompt + ChatOpenAI relevancy scoring."""

    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            model=settings.chat_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )
        self._chain = EVAL_PROMPT | self._llm | StrOutputParser()

    def score(
        self,
        question: str,
        answer: str,
        chunk_texts: list[str],
    ) -> Optional[dict]:
        if not chunk_texts or answer == "No relevant information found.":
            return None
        try:
            import json
            import re

            text = self._chain.invoke(
                {
                    "question": question,
                    "answer": answer,
                    "context": "\n\n".join(chunk_texts[:5]),
                }
            ) or ""
            fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if fence:
                text = fence.group(1)
            data = json.loads(text.strip())
            return {
                "score": float(data.get("score", 0)),
                "passing": bool(data.get("passing", False)),
            }
        except Exception:
            return None
