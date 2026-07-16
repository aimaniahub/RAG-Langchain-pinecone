"""Simple in-process sliding-window rate limiter (Phase 3)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

from app.config import settings


class RateLimiter:
    """Per-key fixed window counter."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, bucket: str, limit_per_minute: int) -> None:
        if not settings.rate_limit_enabled or limit_per_minute <= 0:
            return
        now = time.time()
        window = 60.0
        with self._lock:
            q = self._events[bucket]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded ({limit_per_minute}/min). Retry later.",
                    headers={"Retry-After": "60"},
                )
            q.append(now)


rate_limiter = RateLimiter()


def rate_limit_dependency(kind: str):
    """kind: query | ingest"""

    async def _dep(request: Request) -> None:
        principal = getattr(request.state, "principal", None)
        identity = (
            f"{principal.key_name}:{principal.role}"
            if principal
            else (request.client.host if request.client else "unknown")
        )
        if kind == "query":
            limit = settings.rate_limit_query_per_minute
        else:
            limit = settings.rate_limit_ingest_per_minute
        rate_limiter.check(f"{kind}:{identity}", limit)

    return _dep
