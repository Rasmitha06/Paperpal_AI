from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
REGISTRY_PATH = BASE_DIR / "data" / "doc_registry.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    pinecone_api_key: str = ""
    pinecone_index_name: str = "paperpal"
    pinecone_environment: str = ""  # legacy; optional for serverless
    # Set true if index already exists — skips api.pinecone.io list/create on each upload
    pinecone_skip_index_bootstrap: bool = False

    embedding_model: str = "text-embedding-ada-002"
    chat_model: str = "gpt-4"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    retrieval_top_k: int = 5
    similarity_threshold: float = 0.72

    ocr_enabled: bool = True
    ocr_min_text_chars: int = 80
    ocr_lang: str = "eng"

    vision_enabled: bool = True
    vision_model: str = "gpt-4o-mini"

    # Full-document summary (faster defaults: one-shot when possible, parallel batches)
    summary_model: str = "gpt-4o-mini"
    summary_merge_model: str = ""  # empty = same as summary_model
    summary_one_shot_max_pages: int = 28
    summary_one_shot_max_chars: int = 96_000
    summary_pages_per_batch: int = 10
    summary_max_batch_chars: int = 32_000
    summary_max_page_chars: int = 5_000
    summary_max_workers: int = 4

    jwt_secret: str = "change-me-in-production-use-long-random-string"
    jwt_expire_days: int = 7
    guest_daily_limit: int = 2

    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def save_registry(docs: list[dict]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(docs, indent=2), encoding="utf-8")


def upsert_registry_entry(entry: dict) -> None:
    docs = load_registry()
    docs = [d for d in docs if d.get("doc_id") != entry["doc_id"]]
    docs.append(entry)
    save_registry(docs)


def link_document_owner(doc_id: str, user_id: int) -> None:
    docs = load_registry()
    updated = False
    for doc in docs:
        if doc.get("doc_id") == doc_id:
            doc["owner_user_id"] = user_id
            updated = True
            break
    if updated:
        save_registry(docs)


def list_documents_for_user(user_id: int) -> list[dict]:
    return [
        doc
        for doc in load_registry()
        if doc.get("owner_user_id") == user_id
    ]
