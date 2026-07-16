"""Audit event helpers (Phase 3)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger("audit")


def audit(event: str, **fields: Any) -> None:
    """Emit a structured audit log line (no secrets)."""
    safe = {k: v for k, v in fields.items() if k.lower() not in {"api_key", "authorization", "password"}}
    parts = " ".join(f"{k}={v!r}" for k, v in safe.items())
    logger.info("AUDIT event=%s %s", event, parts)
