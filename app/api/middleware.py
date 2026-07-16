"""HTTP middleware: request ID + access logging (Phase 3)."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger("http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request failed method=%s path=%s request_id=%s latency_ms=%s",
                request.method,
                request.url.path,
                request_id,
                latency_ms,
            )
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "method=%s path=%s status=%s request_id=%s latency_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
            latency_ms,
        )
        return response
