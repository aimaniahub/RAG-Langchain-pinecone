"""RAG API Platform — multi-tenant backend for company integrations.

Primary product: HTTP API + enterprise Admin console.
Clients: API keys + endpoints. Operators: /admin.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import RequestContextMiddleware
from app.api.routes import admin_console, chat, documents, health, ingest, metrics, query
from app.config import get_settings, settings
from app.core.exceptions import AppError, NotConfiguredError, UpstreamError
from app.core.logging import setup_logging

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _log_level() -> int:
    import logging

    return getattr(logging, settings.log_level.upper(), logging.INFO)


logger = setup_logging(level=_log_level(), log_format=settings.log_format)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_settings.cache_clear()
    from app.config import settings as live

    try:
        live.validate_production()
    except RuntimeError as exc:
        logger.error("Startup aborted: %s", exc)
        raise

    if live.auto_migrate:
        try:
            from app.db.session import get_session_factory, init_db
            from app.services.admin_service import AdminService

            init_db()
            db = get_session_factory()()
            try:
                AdminService(db).seed_defaults()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.error("DB init failed: %s", exc)
            if live.is_production:
                raise

    logger.info(
        "Starting %s mode=%s auth=%s admin_ui=%s",
        live.app_name,
        live.product_mode,
        live.auth_enabled,
        live.enable_admin_ui,
    )

    if live.warmup_embeddings:
        try:
            from app.api.deps import get_rag_service

            get_rag_service.cache_clear()
            get_rag_service().warmup()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Warmup failed (continuing): %s", exc)

    yield
    logger.info("Shutting down %s", live.app_name)


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        description=(
            "Enterprise multi-tenant RAG API. "
            "Client companies integrate with API keys. "
            "Operators manage tenants, keys, models, and documents in Admin."
        ),
        version="1.3.0",
        lifespan=lifespan,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
    )

    # CORS first (outermost last registered in Starlette)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    # Pure ASGI request-id logger (must not use BaseHTTPMiddleware — breaks 401 JSON)
    application.add_middleware(RequestContextMiddleware)

    def _err(status: int, message: str, request: Request) -> JSONResponse:
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=status,
            content={"status": "error", "message": message, "request_id": rid},
        )

    @application.exception_handler(NotConfiguredError)
    async def not_configured_handler(request: Request, exc: NotConfiguredError) -> JSONResponse:
        return _err(503, exc.message, request)

    @application.exception_handler(UpstreamError)
    async def upstream_handler(request: Request, exc: UpstreamError) -> JSONResponse:
        msg = exc.message if not settings.is_production else "Upstream provider error"
        return _err(502, msg, request)

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _err(400, exc.message, request)

    prefix = settings.api_prefix.rstrip("/") or "/api/v1"

    # Public / client APIs
    application.include_router(health.router, prefix=prefix)
    application.include_router(query.router, prefix=prefix)
    application.include_router(ingest.router, prefix=prefix)
    application.include_router(documents.router, prefix=prefix)
    application.include_router(metrics.router, prefix=prefix)

    # Enterprise admin console API (single source of truth)
    application.include_router(admin_console.router, prefix=prefix)

    if settings.enable_chat_ui or settings.product_mode == "full_demo":
        application.include_router(chat.router, prefix=prefix)

    if settings.ui_enabled and STATIC_DIR.is_dir():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        if settings.enable_admin_ui:

            @application.get("/admin", include_in_schema=False)
            def admin_page() -> FileResponse:
                return FileResponse(STATIC_DIR / "admin_console.html")

        if settings.enable_chat_ui or settings.product_mode == "full_demo":

            @application.get("/chat", include_in_schema=False)
            def chat_page() -> FileResponse:
                return FileResponse(STATIC_DIR / "chat.html")

        if settings.enable_dev_ui or settings.product_mode == "full_demo":

            @application.get("/ui", include_in_schema=False)
            def ui_page() -> FileResponse:
                return FileResponse(STATIC_DIR / "index.html")

    @application.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": settings.app_name,
            "product": "rag-api-platform",
            "version": "1.3.0",
            "mode": settings.product_mode,
            "message": (
                "Multi-tenant RAG API. Each company has its own namespace, docs, keys, and RAG settings. "
                "Clients must use X-API-Key from that company only."
            ),
            "docs": settings.docs_url or "disabled",
            "health": f"{prefix}/health",
            "ready": f"{prefix}/ready",
            "admin": "/admin" if settings.enable_admin_ui else None,
            "isolation": {
                "rule": "company_api_key → tenant → pinecone_namespace + tenant_id",
                "never_use_admin_key_for_chat": True,
            },
            "client_api": {
                "query": f"POST {prefix}/query",
                "ingest": f"POST {prefix}/ingest",
                "ingest_file": f"POST {prefix}/ingest/file",
                "documents": f"{prefix}/documents",
                "auth": "X-API-Key: <company_api_key>",
            },
            "admin_api": {
                "setup": f"GET {prefix}/admin/setup",
                "onboard": f"POST {prefix}/admin/onboard",
                "tenants": f"{prefix}/admin/tenants",
                "reindex": f"POST {prefix}/admin/tenants/{{id}}/documents/reindex",
                "keys": f"{prefix}/admin/keys",
                "models": f"{prefix}/admin/models",
            },
        }

    return application


app = create_app()
