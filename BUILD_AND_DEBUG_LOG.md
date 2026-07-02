# Paperpal AI — Build & Debug Log

This document describes how **Paperpal AI** was built, what problems came up during development, and how they were fixed. It is meant for anyone reviewing the project (portfolio, GitHub, or onboarding).

---

## 1. What We Built

**Paperpal AI** is a ChatPDF-style app:

- Upload PDFs → extract text, tables, OCR, and vision for charts
- **Chat** with grounded answers and page citations (RAG)
- **Summary** of the full document (every page, brief + detailed)
- User sign-in, guest trial limits, and per-user document/history

**Stack**

| Layer | Tech |
|--------|------|
| Frontend | React 18, Vite (`frontend/`) |
| Backend | FastAPI, Uvicorn (`backend/`) |
| RAG | LangChain + OpenAI embeddings + Pinecone |
| PDF | PyMuPDF, pdfplumber, Tesseract OCR, GPT-4o-mini vision |
| Auth | JWT, SQLite |

---

## 2. How It Was Built (High Level)

### 2.1 Upload pipeline

```
PDF file
  → PyMuPDF text per page
  → OCR if page text is sparse (Tesseract)
  → Tables via pdfplumber
  → Vision pass for figures/charts (optional)
  → LangChain RecursiveCharacterTextSplitter
  → OpenAI embeddings → Pinecone upsert
  → Registry entry in data/doc_registry.json
```

### 2.2 Chat (Q&A)

```
User question
  → Embed query
  → Pinecone similarity search (filtered by doc_id)
  → Chunks above similarity threshold
  → LangChain QA chain (GPT) → Markdown answer + citations
  → Optional relevancy evaluation score
```

### 2.3 Summary (full document)

Originally summary used the same vector search as chat. Broad questions like "summarize this entire document" often returned **no chunks** (similarity below 0.72), so the UI showed *"No relevant information found."*

**Fix:** dedicated summary path in `backend/services/document_summary_service.py`:

1. Read **every page** from the stored PDF in `data/uploads/`
2. **Small PDFs (≤28 pages):** one `gpt-4o-mini` call → Brief + Full summary
3. **Large PDFs:** batch pages (10 per batch), summarize batches **in parallel** (4 workers), then one merge call
4. Exposed as `POST /api/summary` (frontend Summary tab calls this directly)

### 2.4 Auth & privacy

- Guests: 2 operations/day (upload or query)
- Signed-in users: unlimited
- **Documents list** and **history** only when signed in
- Uploads linked to `owner_user_id` in the doc registry
- `.env` holds secrets; `.env.example` is the template for GitHub

### 2.5 UI changes over time

- Removed **Extract** tab (structured JSON / figures gallery)
- Renamed `ui-v1/` → `frontend/`
- Upload success: green checkmark instead of long Pinecone pipeline message
- Summary hint: "Analyzes every page… ~15–40 seconds"

---

## 3. Debugging Issues & Fixes

### 3.1 Summary returned "No relevant information found"

**Symptom:** 23-page PDF (e.g. *Ultimate AI & Automation Resource Sheet*) showed empty summary.

**Cause:** Summary went through `/api/query` with a generic prompt. Vector search with `similarity_threshold=0.72` and `top_k=5` did not match "summarize entire document" to list/table-heavy chunks.

**Fix:**

- `is_summary_query()` detection for chat-style summary prompts
- Full-page read + map-reduce in `document_summary_service.py`
- Dedicated `/api/summary` endpoint
- Lower threshold / multi-query retrieval kept only as fallback if PDF file missing on disk

---

### 3.2 Pinecone upload error (DNS)

**Symptom:**

```
HTTPSConnectionPool(host='api.pinecone.io', port=443): Max retries exceeded
Failed to resolve 'api.pinecone.io'
```

**Cause:** Intermittent DNS/network, or control-plane call on every upload (`list_indexes()`).

**Checks:**

```bash
curl -I https://api.pinecone.io/   # HTTP 401 = reachable (expected without API key)
python3 -c "import socket; print(socket.gethostbyname('api.pinecone.io'))"
```

**Fix:**

- Added `PINECONE_SKIP_INDEX_BOOTSTRAP=true` in `.env` when index already exists in Pinecone console
- Cached index bootstrap in `langchain_stack.py`
- Clearer error message when DNS fails

---

### 3.3 `uvicorn: command not found`

**Cause:** Virtual environment not activated.

**Fix:**

```bash
cd pdf-rag-assistant
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

---

### 3.4 `Address already in use` (port 8000)

**Cause:** Previous backend still running.

**Fix:**

```bash
lsof -ti :8000 | xargs kill
```

---

### 3.5 Git push: `Repository not found`

**Cause:** Remote URL wrong username/repo, or repo not created on GitHub yet.

**Fix:**

1. Create empty repo on GitHub (e.g. `Rasmitha06/Paperpal_AI`)
2. Update remote (do **not** run `git remote add` twice):

```bash
git remote set-url origin https://github.com/Rasmitha06/Paperpal_AI.git
git push -u origin main
```

---

### 3.6 `.env` overwritten with placeholders

**Symptom:** `.env` looked like `.env.example` (`sk-your-openai-key-here`).

**Cause:** Accidentally copied example over real file. `.env` is gitignored — git cannot restore it.

**Fix:** Restore keys from backup or paste again from OpenAI/Pinecone dashboards. Never commit `.env`.

---

### 3.7 History / documents visible when signed out

**Fix:** Frontend only loads documents/history when `user` is set; backend requires auth for `list_documents` and history; guest history no longer merged into signed-in view.

---

### 3.8 Extract tab circular JSON error (before removal)

**Symptom:** Clicking "Run extraction" crashed with circular JSON error.

**Cause:** `onClick={handleExtract}` passed the click event as first argument.

**Fix:** `onClick={() => handleExtract()}` — later the whole Extract feature was removed per product decision.

---

## 4. How to Run Locally

**Terminal 1 — backend**

```bash
cd pdf-rag-assistant
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — frontend**

```bash
cd pdf-rag-assistant/frontend
npm install   # first time only
npm run dev
```

Open: **http://localhost:5173**

**Health check:** http://127.0.0.1:8000/api/health

---

## 5. Optional Verification Scripts

In `scripts/` (not required for the app to run):

| Script | Purpose |
|--------|---------|
| `verify_pinecone.py` | Test Pinecone API key and index |
| `verify_capabilities.py` | End-to-end smoke test (health, OCR, query, anti-hallucination) |

```bash
python scripts/verify_pinecone.py
python scripts/verify_capabilities.py --doc-id "your-file.pdf"
```

---

## 6. Environment Variables (minimum)

Copy `.env.example` → `.env` and set:

```env
OPENAI_API_KEY=...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=documind
PINECONE_SKIP_INDEX_BOOTSTRAP=true
JWT_SECRET=...long-random-string...
CHAT_MODEL=gpt-4o-mini
SUMMARY_MODEL=gpt-4o-mini
```

---

## 7. What to Upload to GitHub

**Include:** `backend/`, `frontend/`, `README.md`, `.env.example`, `.gitignore`, `requirements.txt`, optional `scripts/`, this file.

**Exclude (via `.gitignore`):** `.env`, `.venv/`, `data/`, `frontend/node_modules/`, `frontend/dist/`

---

## 8. Lessons Learned

1. **Full-document summary ≠ semantic search** — use page-level read or map-reduce, not a single retrieval query.
2. **Use a fast model for summaries** (`gpt-4o-mini`) and parallel batches for large PDFs.
3. **Skip Pinecone bootstrap** when the index already exists to reduce failures and latency.
4. **Keep secrets out of git** — only `.env.example` in the repo.
5. **Verify network with `curl`** before blaming application code for Pinecone errors.

---

*Last updated: May 2026*
