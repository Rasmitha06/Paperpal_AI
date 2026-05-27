# Paperpal AI

## Overview

Paperpal AI is a ChatPDF-style application that turns PDFs into a searchable knowledge base. Users upload documents, ask questions with citations, and generate full-document summaries. The system uses retrieval-augmented generation (RAG) with vector search, plus OCR, table extraction, and vision for charts and figures.

The project includes a FastAPI backend, a React + Vite frontend, user authentication with guest trial limits, and per-user document and activity history.

## Problem Statement

Reading long PDFs (reports, resumes, resource sheets, research papers) is slow when you only need specific facts or a high-level overview. Generic chat tools are not grounded in your file and may hallucinate. Paperpal AI addresses this by:

- Indexing each uploaded PDF into a vector database scoped by document
- Answering questions only from retrieved excerpts, with page-level context
- Summarizing every page of a document (brief + full summary), not just a few similar chunks
- Handling scanned pages (OCR), tables, and chart-heavy pages (vision) during ingest

## Tech Stack

| Layer | Technologies |
|--------|----------------|
| **Frontend** | React 18, Vite, Marked (Markdown rendering) |
| **Backend** | FastAPI, Uvicorn, Pydantic Settings |
| **RAG / LLM** | LangChain (LCEL), OpenAI (`gpt-4o-mini` / `gpt-4`), OpenAI Embeddings |
| **Vector DB** | Pinecone (`langchain-pinecone`) |
| **PDF processing** | PyMuPDF (fitz), pdfplumber, Tesseract OCR (optional), GPT-4o-mini vision |
| **Auth & storage** | JWT, SQLite (`documind.db`), bcrypt/passlib |
| **Dev** | Python 3.9+, Node.js 18+ |

## Architecture / Workflow

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  React UI   │────▶│  FastAPI :8000   │────▶│    Pinecone     │
│  :5173      │     │  /api/*          │     │  (embeddings)   │
└─────────────┘     └────────┬─────────┘     └─────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
              ┌──────────┐      ┌──────────────┐
              │ SQLite   │      │ OpenAI API   │
              │ users,   │      │ chat + embed │
              │ history  │      │ + vision     │
              └──────────┘      └──────────────┘
```

### Upload pipeline

1. PDF saved under `data/uploads/`
2. Per-page text: native extract → OCR if sparse → tables (pdfplumber) → vision for figures/charts
3. LangChain `RecursiveCharacterTextSplitter` → chunks with metadata (`doc_id`, `page`, `chunk_id`)
4. Embeddings → upsert to Pinecone; registry entry in `data/doc_registry.json`
5. Signed-in users: document linked to `owner_user_id`; upload recorded in history

### Query pipeline (Chat)

1. Embed question → similarity search in Pinecone filtered by `doc_id`
2. Filter chunks by similarity threshold; boost retrieval for chart-related questions
3. LangChain QA chain → Markdown answer with citations
4. Optional relevancy evaluation score

### Summary pipeline

1. Read **every page** from the stored PDF (not vector search only)
2. **≤28 pages**: single `gpt-4o-mini` pass → Brief + Full summary
3. **Larger PDFs**: parallel batch summaries (10 pages/batch) → one merge call
4. Dedicated endpoint: `POST /api/summary`

## Features

- **PDF upload** with drag-and-drop; OCR, tables, and vision on ingest
- **Chat** with grounded answers, retrieved chunk previews, and relevancy score
- **Full-document summary** (Brief Summary + page-by-page Full Summary)
- **User auth** (sign up / sign in) and **guest trial** (2 operations/day)
- **Documents list** and **activity history** (search, chat, uploads) for signed-in users only
- **Chart-aware Q&A** via `CHART_DATA` chunks from vision at upload time

## Results

- End-to-end RAG: upload → index → query with citations
- Multi-page PDFs (e.g. 23-page resource sheets, 125+ chunks) indexed and queryable
- Summaries typically complete in ~15–40 seconds for medium-length PDFs (one-shot path)
- Guest-friendly demo with usage limits; unlimited use when authenticated

## Screenshots

_Add screenshots of your running app here._

| Screen | Description |
|--------|-------------|
| Home / demo | Hero, Chat / Summary tabs, upload panel |
| Chat | Question, answer with citations and chunk scores |
| Summary | Brief Summary + Full Summary (page headings) |
| Sidebar | Documents list and history (signed in) |

Example paths after capture:

```markdown
![Chat](docs/screenshots/chat.png)
![Summary](docs/screenshots/summary.png)
```

## Folder Structure

```
pdf-rag-assistant/
├── backend/
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # Settings, registry, env
│   ├── database.py             # SQLite schema
│   ├── deps.py                 # Auth, guest limits
│   ├── models/                 # Pydantic request/response models
│   ├── routes/
│   │   ├── auth.py
│   │   ├── upload.py
│   │   ├── query.py
│   │   ├── summary.py
│   │   ├── list_documents.py
│   │   └── history.py
│   └── services/
│       ├── pdf_processor.py
│       ├── ocr_service.py
│       ├── vision_service.py
│       ├── langchain_stack.py  # Pinecone, retrieval, QA chains
│       ├── document_summary_service.py
│       ├── llm_service.py
│       ├── vector_store.py
│       ├── history_service.py
│       └── auth_service.py
├── frontend/                   # React + Vite frontend
│   ├── src/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── api.js
│   │   └── AuthModal.jsx
│   └── vite.config.ts          # Proxies /api → :8000
├── scripts/
│   ├── verify_capabilities.py
│   └── verify_pinecone.py
├── data/                       # gitignored: uploads, registry, db
├── requirements.txt
├── .env.example
└── README.md
```

## Installation

### Prerequisites

- Python 3.9+
- Node.js 18+
- [Pinecone](https://www.pinecone.io/) account and API key
- [OpenAI](https://platform.openai.com/) API key
- Optional: `brew install tesseract` for scanned PDFs

### 1. Clone and configure

```bash
cd pdf-rag-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` (minimum):

```env
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=pcsk-...
PINECONE_INDEX_NAME=your-index-name
JWT_SECRET=your-long-random-secret

# If index already exists in Pinecone console (skips control-plane check)
PINECONE_SKIP_INDEX_BOOTSTRAP=true

# Fast summaries
SUMMARY_MODEL=gpt-4o-mini
```

### 2. Run backend

```bash
uvicorn backend.main:app --reload --port 8000
```

If port 8000 is in use:

```bash
lsof -ti :8000 | xargs kill
```

Health check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

### 3. Run frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

### 4. Verify (optional)

```bash
python scripts/verify_capabilities.py --doc-id "your-file.pdf"
python scripts/verify_pinecone.py
```

### API reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload` | POST | Upload PDF → index in Pinecone |
| `/api/query` | POST | Ask a question (`doc_id`, `question`) |
| `/api/summary` | POST | Full-document summary (`doc_id`) |
| `/api/list_documents` | GET | List user's PDFs (auth required) |
| `/api/history` | GET | Activity history (auth required) |
| `/api/auth/signup` | POST | Create account |
| `/api/auth/signin` | POST | Sign in |
| `/api/health` | GET | Health check |

## Future Improvements

- Summary caching per `doc_id` to avoid re-processing on repeat requests
- Streaming responses for chat and summary in the UI
- PDF highlight / jump-to-page from citations
- Admin dashboard for usage and index stats
- Support for more embedding models and local LLM providers
- Batch upload and folder-based document collections
- Export summary and chat transcripts (PDF / Markdown)
- Stronger chart Q&A with dedicated figure index browsing
