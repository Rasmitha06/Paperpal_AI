from __future__ import annotations

from typing import List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone, ServerlessSpec

from backend.config import load_registry, settings, upsert_registry_entry

NO_INFO = "No relevant information found."

QA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are Paperpal AI, a document Q&A assistant.
Answer using ONLY the provided document excerpts.

Rules:
- Do not speculate or use outside knowledge.
- If excerpts do not contain the answer, reply exactly: No relevant information found.
- ALWAYS format answers in clean Markdown with clear structure.
- Use ## for main sections, ### for subsections.
- Use numbered lists (1. 2. 3.) for ordered items.
- Use bullet lists (- ) for supporting details.
- Put blank lines between sections and list items.
- Bold (**text**) key terms, dates, metrics, and names.
- Cite page numbers inline, e.g. (page 3).""",
        ),
        (
            "human",
            """Document excerpts:

{context}

Question: {question}

Write a well-organized Markdown answer based ONLY on the excerpts above.

Format requirements:
- Start with ## Answer (1–2 sentence direct answer)
- Use ## and ### headings to group topics
- Use numbered lists for distinct items; bullets for details under each
- End with ## Sources Used listing page numbers referenced""",
        ),
    ]
)

SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are Paperpal AI. Write a grounded summary using ONLY the document excerpts.

Rules:
- Synthesize across all excerpts into one coherent summary of the full document.
- Cover the main purpose, major themes/sections, and important items (tools, links, lists, facts).
- Do not use outside knowledge.
- If excerpts contain substantive text, never reply with "No relevant information found."
- Use clean Markdown: ## for sections, bullets and numbered lists where helpful.
- Cite page numbers inline, e.g. (page 3).""",
        ),
        (
            "human",
            """Document excerpts (from across the PDF):

{context}

User request: {question}

Write a comprehensive Markdown document summary based ONLY on the excerpts above.

Format:
- Start with ## Summary (2–4 sentences on what this document is)
- Use ## and ### for major themes or sections
- Use bullets for lists of tools, resources, or key points
- End with ## Sources Used (page numbers referenced)""",
        ),
    ]
)

SUMMARY_RETRIEVAL_SEEDS = (
    "document overview main sections topics key content purpose summary",
    "artificial intelligence automation tools resources platforms links list",
    "introduction features categories recommendations guide sheet",
)


_index_bootstrap_done = False


def _ensure_pinecone_index() -> None:
    """Verify or create Pinecone index (control plane). Skipped when bootstrap is disabled."""
    global _index_bootstrap_done
    if _index_bootstrap_done or settings.pinecone_skip_index_bootstrap:
        return
    if not settings.pinecone_api_key:
        raise ValueError("PINECONE_API_KEY is required.")

    try:
        pc = Pinecone(api_key=settings.pinecone_api_key)
        existing = {idx.name for idx in pc.list_indexes()}
        if settings.pinecone_index_name in existing:
            _index_bootstrap_done = True
            return
        pc.create_index(
            name=settings.pinecone_index_name,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        _index_bootstrap_done = True
    except Exception as exc:
        err = str(exc).lower()
        if "nodename nor servname" in err or "failed to resolve" in err:
            raise ValueError(
                "Cannot reach Pinecone (DNS/network). Check internet/VPN, then run: "
                "curl -I https://api.pinecone.io/ — or set PINECONE_SKIP_INDEX_BOOTSTRAP=true "
                "if your index already exists in the Pinecone console."
            ) from exc
        raise


def get_embeddings() -> OpenAIEmbeddings:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required.")
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
    )


def get_llm() -> ChatOpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required.")
    return ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


def get_vectorstore() -> PineconeVectorStore:
    if not settings.pinecone_api_key:
        raise ValueError("PINECONE_API_KEY is required.")
    _ensure_pinecone_index()
    return PineconeVectorStore(
        index_name=settings.pinecone_index_name,
        embedding=get_embeddings(),
        pinecone_api_key=settings.pinecone_api_key,
    )


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def chunks_to_documents(
    doc_id: str, filename: str, chunks: list[dict]
) -> Tuple[List[Document], List[str]]:
    documents = []
    ids = []
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        documents.append(
            Document(
                page_content=chunk["text"],
                metadata={
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "page": chunk["page"],
                    "filename": filename,
                    "content_type": chunk.get("content_type", "text"),
                },
            )
        )
        ids.append(f"{doc_id}::{chunk_id}")
    return documents, ids


def ingest_chunks(
    doc_id: str,
    filename: str,
    page_count: int,
    chunks: list[dict],
) -> int:
    vectorstore = get_vectorstore()
    documents, ids = chunks_to_documents(doc_id, filename, chunks)
    vectorstore.add_documents(documents=documents, ids=ids)
    upsert_registry_entry(
        {
            "doc_id": doc_id,
            "filename": filename,
            "page_count": page_count,
            "chunk_count": len(chunks),
        }
    )
    return len(chunks)


CHART_QUERY_BOOST = (
    " CHART_DATA figure chart graph pie percentage color segment legend slice "
)


def is_chart_query(question: str) -> bool:
    q = question.lower()
    return any(
        k in q
        for k in (
            "fig",
            "figure",
            "chart",
            "graph",
            "pie",
            "%",
            "percent",
            "color",
            "colour",
            "red",
            "blue",
            "green",
            "orange",
            "slice",
            "segment",
            "legend",
        )
    )


def is_summary_query(question: str) -> bool:
    q = question.lower().strip()
    return any(
        phrase in q
        for phrase in (
            "summary",
            "summarize",
            "summarise",
            "overview of",
            "entire document",
            "full document",
            "whole document",
            "comprehensive summary",
        )
    )


def _search_chunks(
    question: str,
    doc_id: str,
    *,
    chunk_id: Optional[str] = None,
    k: int,
    score_threshold: Optional[float],
) -> list[dict]:
    vectorstore = get_vectorstore()
    filt: dict = {"doc_id": {"$eq": doc_id}}
    if chunk_id:
        filt["chunk_id"] = {"$eq": chunk_id}

    results = vectorstore.similarity_search_with_score(
        question,
        k=k,
        filter=filt,
    )

    matches = []
    for doc, score in results:
        if score_threshold is not None and score < score_threshold:
            continue
        meta = doc.metadata or {}
        matches.append(
            {
                "chunk_id": meta.get("chunk_id", ""),
                "page": int(meta.get("page", 0)),
                "text": doc.page_content,
                "score": float(score),
            }
        )
    return matches


def retrieve_summary_chunks(doc_id: str, question: str) -> list[dict]:
    """Broad retrieval for full-document summaries (lower threshold, more chunks)."""
    seen: dict[str, dict] = {}
    queries = [question, *SUMMARY_RETRIEVAL_SEEDS]

    for q in queries:
        for chunk in _search_chunks(
            q, doc_id, k=12, score_threshold=0.42
        ):
            seen.setdefault(chunk["chunk_id"], chunk)

    if len(seen) < 4:
        for chunk in _search_chunks(
            SUMMARY_RETRIEVAL_SEEDS[0],
            doc_id,
            k=18,
            score_threshold=None,
        ):
            seen.setdefault(chunk["chunk_id"], chunk)

    chunks = sorted(seen.values(), key=lambda c: (c["page"], c["chunk_id"]))
    return chunks[:16]


def retrieve_chunks(
    question: str,
    doc_id: str,
    chunk_id: Optional[str] = None,
    score_threshold: Optional[float] = None,
    top_k: Optional[int] = None,
) -> list[dict]:
    threshold = (
        score_threshold
        if score_threshold is not None
        else settings.similarity_threshold
    )

    search_query = question
    k = top_k or settings.retrieval_top_k
    if is_chart_query(question):
        search_query = question + CHART_QUERY_BOOST
        k = max(k, 8)
        threshold = min(threshold, 0.58)

    return _search_chunks(
        search_query,
        doc_id,
        chunk_id=chunk_id,
        k=k,
        score_threshold=threshold,
    )


def format_context(chunks: list[dict]) -> str:
    blocks = []
    for c in chunks:
        blocks.append(
            f"[chunk_id={c['chunk_id']} | page={c['page']} | score={c['score']:.3f}]\n{c['text']}"
        )
    return "\n\n---\n\n".join(blocks)


def build_qa_chain():
    """LangChain LCEL: context + question → formatted Markdown answer."""
    return QA_PROMPT | get_llm() | StrOutputParser()


def build_summary_chain():
    return SUMMARY_PROMPT | get_llm() | StrOutputParser()


def generate_answer(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return NO_INFO
    chain = build_qa_chain()
    return chain.invoke(
        {"context": format_context(chunks), "question": question}
    ).strip() or NO_INFO


def generate_summary_answer(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return NO_INFO
    chain = build_summary_chain()
    return chain.invoke(
        {"context": format_context(chunks), "question": question}
    ).strip() or NO_INFO


def list_documents() -> list[dict]:
    return load_registry()
