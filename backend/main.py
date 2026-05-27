from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import init_db
from backend.routes import auth, history, list_documents, query, summary, upload

load_dotenv()
init_db()

app = FastAPI(
    title="Paperpal AI",
    description="PDF RAG with LangChain, Pinecone, and GPT-4",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(query.router)
app.include_router(summary.router)
app.include_router(list_documents.router)
app.include_router(history.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Paperpal AI"}
