"""Usage aggregates for admin dashboard."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import ChatMessage, ChatSession, Document, UsageEvent
from app.services.metrics_store import metrics_store


class UsageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(self) -> dict:
        query_count = (
            self.db.query(func.count(UsageEvent.id))
            .filter(UsageEvent.event_type == "query")
            .scalar()
            or 0
        )
        ingest_count = (
            self.db.query(func.count(UsageEvent.id))
            .filter(UsageEvent.event_type == "ingest")
            .scalar()
            or 0
        )
        avg_latency = (
            self.db.query(func.avg(UsageEvent.latency_ms))
            .filter(UsageEvent.event_type == "query", UsageEvent.latency_ms.isnot(None))
            .scalar()
        )
        docs_ready = (
            self.db.query(func.count(Document.id))
            .filter(Document.status == "ready")
            .scalar()
            or 0
        )
        docs_failed = (
            self.db.query(func.count(Document.id))
            .filter(Document.status == "failed")
            .scalar()
            or 0
        )
        docs_total = self.db.query(func.count(Document.id)).scalar() or 0
        sessions = self.db.query(func.count(ChatSession.id)).scalar() or 0
        messages = self.db.query(func.count(ChatMessage.id)).scalar() or 0

        # lag stage histogram from DB
        lag_rows = (
            self.db.query(UsageEvent.lag_stage, func.count(UsageEvent.id))
            .filter(UsageEvent.event_type == "query", UsageEvent.lag_stage.isnot(None))
            .group_by(UsageEvent.lag_stage)
            .all()
        )
        lag_counts = {str(k): int(v) for k, v in lag_rows if k}

        # merge live in-memory metrics if present
        live = metrics_store.summary()

        return {
            "query_count": int(query_count),
            "ingest_count": int(ingest_count),
            "avg_latency_ms": int(avg_latency) if avg_latency is not None else None,
            "documents_total": int(docs_total),
            "documents_ready": int(docs_ready),
            "documents_failed": int(docs_failed),
            "chat_sessions": int(sessions),
            "chat_messages": int(messages),
            "lag_stage_counts": lag_counts,
            "live_metrics": live,
        }

    def recent_events(self, limit: int = 50) -> list[UsageEvent]:
        return (
            self.db.query(UsageEvent)
            .order_by(UsageEvent.created_at.desc())
            .limit(limit)
            .all()
        )
