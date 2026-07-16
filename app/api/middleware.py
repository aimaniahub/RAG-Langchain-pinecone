"""HTTP middleware: request ID + access logging (ASGI — safe with HTTPException)."""

from __future__ import annotations

import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

logger = get_logger("http")


class RequestContextMiddleware:
    """Pure ASGI middleware.

    Avoids Starlette BaseHTTPMiddleware, which can turn FastAPI HTTPException
    (401/403) into opaque 500 responses in production.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers") or []
        }
        request_id = headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        status_code_box = {"code": 500}

        # Expose request_id on scope state for handlers
        state = scope.setdefault("state", {})
        if not isinstance(state, dict):
            # Starlette may use a State object
            try:
                setattr(state, "request_id", request_id)
            except Exception:  # noqa: BLE001
                scope["state"] = type("S", (), {"request_id": request_id})()
        else:
            state["request_id"] = request_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code_box["code"] = int(message.get("status", 500))
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request failed method=%s path=%s request_id=%s latency_ms=%s",
                scope.get("method"),
                scope.get("path"),
                request_id,
                latency_ms,
            )
            raise
        else:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "method=%s path=%s status=%s request_id=%s latency_ms=%s",
                scope.get("method"),
                scope.get("path"),
                status_code_box["code"],
                request_id,
                latency_ms,
            )
