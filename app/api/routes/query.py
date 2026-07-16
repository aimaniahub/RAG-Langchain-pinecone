"""RAG query routes + streaming (S0/S1)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_rag_service
from app.config import settings
from app.core.audit import audit
from app.core.exceptions import AppError, NotConfiguredError, QueryError, UpstreamError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit_dependency
from app.core.security import Principal, require_roles
from app.models.schemas import QueryRequest, QueryResponse
from app.services.rag_service import RAGService

router = APIRouter(tags=["query"])
logger = get_logger("api.query")


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotConfiguredError):
        return HTTPException(status_code=503, detail=exc.message)
    if isinstance(exc, QueryError):
        return HTTPException(status_code=400, detail=exc.message)
    if isinstance(exc, UpstreamError):
        return HTTPException(status_code=502, detail=exc.message)
    if isinstance(exc, AppError):
        return HTTPException(status_code=500, detail=exc.message)
    logger.exception("Unhandled query error")
    return HTTPException(status_code=500, detail="Internal server error")


def _validate_question(body: QueryRequest) -> None:
    if len(body.question) > settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Question too long (max {settings.max_question_chars} chars)",
        )


@router.post("/query", response_model=QueryResponse)
def query_rag(
    body: QueryRequest,
    request: Request,
    principal: Principal = Depends(require_roles("admin", "user")),
    _: None = Depends(rate_limit_dependency("query")),
    service: RAGService = Depends(get_rag_service),
) -> QueryResponse:
    """Answer via RAG with timings, cache, rerank, compressed context."""
    _validate_question(body)
    logger.info(
        "POST /query actor=%s question_len=%s",
        principal.key_name,
        len(body.question),
    )
    try:
        result = service.query(body)
        audit(
            "query.completed",
            actor=principal.key_name,
            role=principal.role,
            sources=len(result.sources),
            question_len=len(body.question),
            lag=result.lag_stage,
            total_ms=(result.timings_ms or {}).get("total"),
            request_id=getattr(request.state, "request_id", None),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        audit(
            "query.failed",
            actor=principal.key_name,
            error=str(exc)[:200],
            request_id=getattr(request.state, "request_id", None),
        )
        raise _map_error(exc) from exc


@router.post("/query/stream")
def query_rag_stream(
    body: QueryRequest,
    request: Request,
    principal: Principal = Depends(require_roles("admin", "user")),
    _: None = Depends(rate_limit_dependency("query")),
    service: RAGService = Depends(get_rag_service),
) -> StreamingResponse:
    """SSE stream: stage timings + tokens + final JSON."""
    _validate_question(body)
    if not settings.streaming_enabled:
        raise HTTPException(status_code=400, detail="Streaming disabled")

    def event_gen():
        try:
            for item in service.stream_query(body):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            yield "data: {\"event\":\"done\"}\n\n"
        except Exception as exc:  # noqa: BLE001
            err = {"event": "error", "message": str(exc)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
