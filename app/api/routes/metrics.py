"""Latency monitor API for the UI graphs (S0)."""

from fastapi import APIRouter, Depends, Query

from app.core.security import Principal, require_roles
from app.models.schemas import MetricsSummaryResponse
from app.services.cache_service import cache_service
from app.services.metrics_store import metrics_store

router = APIRouter(tags=["metrics"])


@router.get("/metrics/summary", response_model=MetricsSummaryResponse)
def metrics_summary(
    principal: Principal = Depends(require_roles("admin", "user")),
) -> MetricsSummaryResponse:
    """Aggregated p50/p95 and stage shares for Monitor tab."""
    _ = principal
    summary = metrics_store.summary()
    summary["cache_stats"] = cache_service.stats()
    return MetricsSummaryResponse(**summary)


@router.get("/metrics/queries")
def metrics_queries(
    limit: int = Query(default=40, ge=1, le=200),
    principal: Principal = Depends(require_roles("admin", "user")),
) -> dict:
    """Recent query timing events for charts."""
    _ = principal
    return {"items": metrics_store.recent(limit=limit)}


@router.delete("/metrics")
def metrics_clear(
    principal: Principal = Depends(require_roles("admin")),
) -> dict:
    """Clear in-memory metrics (admin)."""
    _ = principal
    metrics_store.clear()
    return {"status": "ok", "message": "metrics cleared"}
