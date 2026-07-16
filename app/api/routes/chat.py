"""Persistent chat API."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotConfiguredError, UpstreamError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit_dependency
from app.core.security import Principal, require_roles
from app.db.session import get_db
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"])
logger = get_logger("api.chat")


class CreateSessionBody(BaseModel):
    title: str = "New chat"
    namespace: str | None = None


class AskBody(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)


def _map(exc: Exception) -> HTTPException:
    if isinstance(exc, NotConfiguredError):
        return HTTPException(status_code=503, detail=exc.message)
    if isinstance(exc, UpstreamError):
        return HTTPException(status_code=502, detail=exc.message)
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.message)
    logger.exception("chat error")
    return HTTPException(status_code=500, detail="Internal server error")


def _session_dict(s) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "namespace": s.namespace,
        "user_name": s.user_name,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _message_dict(m) -> dict:
    sources = []
    if m.sources_json:
        try:
            sources = json.loads(m.sources_json)
        except json.JSONDecodeError:
            sources = []
    timings = None
    if m.timings_json:
        try:
            timings = json.loads(m.timings_json)
        except json.JSONDecodeError:
            timings = None
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "sources": sources,
        "timings_ms": timings,
        "model": m.model,
        "lag_stage": m.lag_stage,
        "cache_hit": m.cache_hit,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/chat/sessions")
def create_session(
    body: CreateSessionBody,
    principal: Principal = Depends(require_roles("admin", "user")),
    db: Session = Depends(get_db),
) -> dict:
    s = ChatService(db).create_session(
        title=body.title,
        namespace=body.namespace,
        user_name=principal.key_name,
    )
    return {"status": "ok", "session": _session_dict(s)}


@router.get("/chat/sessions")
def list_sessions(
    principal: Principal = Depends(require_roles("admin", "user")),
    db: Session = Depends(get_db),
) -> dict:
    items = ChatService(db).list_sessions(user_name=principal.key_name)
    # admins see all if role admin? keep own for privacy; admin can see all
    if principal.role == "admin":
        items = ChatService(db).list_sessions(limit=100)
    return {"items": [_session_dict(s) for s in items]}


@router.get("/chat/sessions/{session_id}")
def get_session(
    session_id: str,
    principal: Principal = Depends(require_roles("admin", "user")),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    svc = ChatService(db)
    s = svc.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = svc.get_messages(session_id)
    return {
        "session": _session_dict(s),
        "messages": [_message_dict(m) for m in msgs],
    }


@router.post("/chat/sessions/{session_id}/messages")
def ask_in_session(
    session_id: str,
    body: AskBody,
    principal: Principal = Depends(require_roles("admin", "user")),
    _: None = Depends(rate_limit_dependency("query")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        user_msg, assistant = ChatService(db).ask(
            session_id=session_id,
            question=body.question,
            top_k=body.top_k,
            user_name=principal.key_name,
        )
        return {
            "status": "ok",
            "user_message": _message_dict(user_msg),
            "assistant_message": _message_dict(assistant),
        }
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc
