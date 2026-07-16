"""Chat sessions with persistent history + RAG."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.db.models import ChatMessage, ChatSession, UsageEvent
from app.models.schemas import QueryRequest
from app.services.rag_service import RAGService

logger = get_logger("services.chat")


class ChatService:
    def __init__(self, db: Session, rag_service: RAGService | None = None) -> None:
        self.db = db
        self.rag = rag_service or RAGService()

    def create_session(
        self,
        title: str = "New chat",
        namespace: str | None = None,
        user_name: str | None = None,
    ) -> ChatSession:
        session = ChatSession(
            title=(title or "New chat")[:256],
            namespace=namespace or settings.pinecone_namespace or "default",
            user_name=user_name,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def list_sessions(self, limit: int = 50, user_name: str | None = None) -> list[ChatSession]:
        q = self.db.query(ChatSession).order_by(ChatSession.updated_at.desc())
        if user_name:
            q = q.filter(ChatSession.user_name == user_name)
        return q.limit(limit).all()

    def get_session(self, session_id: str) -> ChatSession | None:
        return self.db.get(ChatSession, session_id)

    def get_messages(self, session_id: str) -> list[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )

    def ask(
        self,
        session_id: str,
        question: str,
        top_k: int | None = None,
        user_name: str | None = None,
    ) -> tuple[ChatMessage, ChatMessage]:
        session = self.get_session(session_id)
        if not session:
            raise AppError("Chat session not found")

        question = (question or "").strip()
        if not question:
            raise AppError("Question is required")

        user_msg = ChatMessage(
            session_id=session_id,
            role="user",
            content=question,
        )
        self.db.add(user_msg)
        self.db.commit()

        # auto-title from first question
        if session.title in {"New chat", "new chat", ""}:
            session.title = question[:80]

        resp = self.rag.query(
            QueryRequest(
                question=question,
                top_k=top_k,
                namespace=session.namespace,
                include_timings=True,
            )
        )

        assistant = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=resp.answer,
            sources_json=json.dumps([s.model_dump() for s in resp.sources], ensure_ascii=False),
            timings_json=json.dumps(resp.timings_ms or {}, ensure_ascii=False),
            model=resp.model,
            lag_stage=resp.lag_stage,
            cache_hit=resp.cache_hit,
        )
        self.db.add(assistant)

        total_ms = (resp.timings_ms or {}).get("total")
        self.db.add(
            UsageEvent(
                event_type="query",
                user_name=user_name or session.user_name,
                session_id=session_id,
                latency_ms=total_ms,
                lag_stage=resp.lag_stage,
                cache_hit=resp.cache_hit,
                context_tokens_est=resp.context_tokens_est,
                model=resp.model,
            )
        )
        session.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user_msg)
        self.db.refresh(assistant)
        logger.info(
            "chat ask session=%s total_ms=%s lag=%s",
            session_id,
            total_ms,
            resp.lag_stage,
        )
        return user_msg, assistant
