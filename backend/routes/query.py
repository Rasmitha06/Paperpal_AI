from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.config import settings
from backend.deps import record_operation, require_operation_slot
from backend.services.history_service import filename_for_doc, save_search_history
from backend.models.document import QueryRequest, QueryResponse, RetrievedChunk
from backend.services.evaluation_service import EvaluationService
from backend.services.llm_service import LLMService, NO_INFO
from backend.services.document_summary_service import summarize_full_document
from backend.services.langchain_stack import is_chart_query, is_summary_query
from backend.services.vector_store import VectorStore

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_document(
    body: QueryRequest,
    identity: dict = Depends(require_operation_slot),
):
    try:
        summary_mode = is_summary_query(body.question)

        if summary_mode:
            answer = summarize_full_document(body.doc_id)
            if not answer or answer == NO_INFO:
                record_operation(identity)
                if identity["type"] == "user":
                    save_search_history(
                        identity,
                        body.doc_id,
                        filename_for_doc(body.doc_id),
                        body.question,
                        NO_INFO,
                        None,
                        [],
                    )
                return QueryResponse(
                    answer=NO_INFO,
                    retrieved_chunks=[],
                    relevancy_score=None,
                    relevancy_passing=None,
                )
            relevant = []
            eval_result = None
        else:
            store = VectorStore()
            matches = store.query(
                question=body.question,
                doc_id=body.doc_id,
                chunk_id=body.chunk_id,
            )

            threshold = settings.similarity_threshold
            if is_chart_query(body.question):
                threshold = min(threshold, 0.58)

            relevant = [m for m in matches if m["score"] >= threshold]

            if not relevant:
                record_operation(identity)
                if identity["type"] == "user":
                    save_search_history(
                        identity,
                        body.doc_id,
                        filename_for_doc(body.doc_id),
                        body.question,
                        NO_INFO,
                        None,
                        [],
                    )
                return QueryResponse(
                    answer=NO_INFO,
                    retrieved_chunks=[],
                    relevancy_score=None,
                    relevancy_passing=None,
                )

            llm = LLMService()
            answer = llm.generate_answer(body.question, relevant)

            eval_result = EvaluationService().score(
                question=body.question,
                answer=answer,
                chunk_texts=[m["text"] for m in relevant],
            )

        retrieved = [
            RetrievedChunk(
                chunk_id=m["chunk_id"],
                page=m["page"],
                score=m["score"],
                text=m["text"],
            )
            for m in relevant
        ]

        record_operation(identity)

        if identity["type"] == "user":
            save_search_history(
                identity,
                body.doc_id,
                filename_for_doc(body.doc_id),
                body.question,
                answer,
                eval_result["score"] if eval_result else None,
                relevant,
            )

        return QueryResponse(
            answer=answer,
            retrieved_chunks=retrieved,
            relevancy_score=eval_result["score"] if eval_result else None,
            relevancy_passing=eval_result["passing"] if eval_result else None,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Query failed: {exc}") from exc
