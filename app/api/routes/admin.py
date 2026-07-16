"""Admin dashboard / usage routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import Principal, require_roles
from app.db.session import check_db, get_db
from app.services.usage_service import UsageService
from app.storage.s3_client import get_storage

router = APIRouter(tags=["admin"])


@router.get("/admin/dashboard")
def dashboard(
    principal: Principal = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    usage = UsageService(db).summary()
    storage_ok = False
    try:
        storage_ok = get_storage().health_check()
    except Exception:  # noqa: BLE001
        storage_ok = False

    return {
        "status": "ok",
        "actor": principal.key_name,
        "integrations": {
            "database": check_db(),
            "storage": storage_ok,
            "storage_backend": settings.storage_backend,
            "openrouter": settings.is_openrouter_configured,
            "pinecone": settings.is_pinecone_configured,
        },
        "usage": usage,
        "speed_features": {
            "rerank": settings.rerank_enabled,
            "embed_cache": settings.embed_cache_enabled,
            "answer_cache": settings.answer_cache_enabled,
            "retrieve_top_k": settings.retrieve_top_k,
            "return_top_n": settings.return_top_n,
        },
    }


@router.get("/admin/usage/events")
def usage_events(
    limit: int = 50,
    principal: Principal = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    events = UsageService(db).recent_events(limit=limit)
    return {
        "items": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "user_name": e.user_name,
                "session_id": e.session_id,
                "document_id": e.document_id,
                "latency_ms": e.latency_ms,
                "lag_stage": e.lag_stage,
                "cache_hit": e.cache_hit,
                "context_tokens_est": e.context_tokens_est,
                "model": e.model,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    }
