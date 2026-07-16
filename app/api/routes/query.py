"""Public RAG query endpoints (tenant-scoped via API key)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_rag_service
from app.config import settings
from app.core.audit import audit
from app.core.exceptions import AppError, NotConfiguredError, QueryError, UpstreamError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit_dependency
from app.core.security import Principal, require_scopes
from app.db.models import UsageEvent
from app.db.session import get_db
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


def _load_tenant_config(db: Session, principal: Principal):
    from app.db.models import Tenant
    from app.models.tenant_config import TenantRagConfig

    if not principal.tenant_id:
        return TenantRagConfig(default_model=principal.openrouter_model)
    t = db.get(Tenant, principal.tenant_id)
    cfg = TenantRagConfig.from_tenant(t)
    if not cfg.default_model:
        cfg.default_model = principal.openrouter_model
    return cfg


def _validate_question(body: QueryRequest, max_chars: int | None = None) -> None:
    limit = max_chars or settings.max_question_chars
    if len(body.question) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"Question too long (max {limit} chars)",
        )


def _apply_tenant(body: QueryRequest, principal: Principal) -> QueryRequest:
    """Force namespace from API key tenant (clients cannot escape isolation)."""
    data = body.model_dump()
    data["namespace"] = principal.namespace
    return QueryRequest(**data)


@router.post("/query", response_model=QueryResponse)
def query_rag(
    body: QueryRequest,
    request: Request,
    principal: Principal = Depends(require_scopes("query:read")),
    _: None = Depends(rate_limit_dependency("query")),
    service: RAGService = Depends(get_rag_service),
    db: Session = Depends(get_db),
) -> QueryResponse:
    """Tenant-scoped RAG query for client company integrations."""
    tcfg = _load_tenant_config(db, principal)
    _validate_question(body, tcfg.effective_max_question_chars())
    body = _apply_tenant(body, principal)
    logger.info(
        "POST /query actor=%s tenant=%s ns=%s",
        principal.key_name,
        principal.tenant_id,
        principal.namespace,
    )
    try:
        result = service.query(
            body,
            model_override=principal.openrouter_model or tcfg.default_model,
            tenant_config=tcfg,
        )
        db.add(
            UsageEvent(
                event_type="query",
                tenant_id=principal.tenant_id,
                api_key_id=principal.api_key_db_id,
                user_name=principal.key_name,
                latency_ms=(result.timings_ms or {}).get("total"),
                lag_stage=result.lag_stage,
                cache_hit=result.cache_hit,
                context_tokens_est=result.context_tokens_est,
                model=result.model,
            )
        )
        db.commit()
        audit(
            "query.completed",
            actor=principal.key_name,
            tenant=principal.tenant_id,
            sources=len(result.sources),
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
    principal: Principal = Depends(require_scopes("query:read")),
    _: None = Depends(rate_limit_dependency("query")),
    service: RAGService = Depends(get_rag_service),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE stream (feature-flagged). Namespace forced from API key."""
    tcfg = _load_tenant_config(db, principal)
    _validate_question(body, tcfg.effective_max_question_chars())
    body = _apply_tenant(body, principal)
    if not settings.streaming_enabled:
        raise HTTPException(status_code=400, detail="Streaming disabled")

    def event_gen():
        try:
            for item in service.stream_query(
                body,
                model_override=principal.openrouter_model or tcfg.default_model,
                tenant_config=tcfg,
            ):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            yield 'data: {"event":"done"}\n\n'
        except Exception as exc:  # noqa: BLE001
            err = {"event": "error", "message": str(exc)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
