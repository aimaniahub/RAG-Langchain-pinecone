"""FastAPI entrypoint — Railway-ready Company RAG.

UIs:
  /chat   — persistent chat
  /admin  — documents, usage, monitors
  /ui     — legacy speed console

Run:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import RequestContextMiddleware
from app.api.routes import admin, chat, documents, health, ingest, metrics, query
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
            from app.db.session import init_db

            init_db()
        except Exception as exc:  # noqa: BLE001
            logger.error("DB init failed: %s", exc)
            if live.is_production:
                raise

    logger.info(
        "Starting %s env=%s phase=%s auth=%s db=%s storage=%s openrouter=%s pinecone=%s",
        live.app_name,
        live.app_env,
        live.phase,
        live.auth_enabled,
        live.database_url.split(":")[0],
        live.storage_backend,
        live.is_openrouter_configured,
        live.is_pinecone_configured,
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
            "Company RAG — Railway production path. "
            "Postgres · S3/local storage · chat · admin · Pinecone · OpenRouter"
        ),
        version="0.4.0",
        lifespan=lifespan,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
    )

    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

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
    application.include_router(health.router, prefix=prefix)
    application.include_router(ingest.router, prefix=prefix)
    application.include_router(query.router, prefix=prefix)
    application.include_router(metrics.router, prefix=prefix)
    application.include_router(documents.router, prefix=prefix)
    application.include_router(chat.router, prefix=prefix)
    application.include_router(admin.router, prefix=prefix)

    if settings.ui_enabled and STATIC_DIR.is_dir():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @application.get("/chat", include_in_schema=False)
        def chat_page() -> FileResponse:
            return FileResponse(STATIC_DIR / "chat.html")

        @application.get("/admin", include_in_schema=False)
        def admin_page() -> FileResponse:
            return FileResponse(STATIC_DIR / "admin.html")

        @application.get("/ui", include_in_schema=False)
        def ui_page() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

        @application.get("/", include_in_schema=False)
        def root_redirect() -> RedirectResponse:
            return RedirectResponse(url="/chat")

    else:

        @application.get("/")
        def root() -> dict:
            return {
                "app": settings.app_name,
                "phase": settings.phase,
                "health": f"{prefix}/health",
            }

    @application.get("/api")
    def api_info() -> dict:
        return {
            "app": settings.app_name,
            "phase": settings.phase,
            "docs": settings.docs_url or "disabled",
            "health": f"{prefix}/health",
            "ready": f"{prefix}/ready",
            "chat_ui": "/chat",
            "admin_ui": "/admin",
            "dev_ui": "/ui",
            "auth_enabled": settings.auth_enabled,
            "storage": settings.storage_backend,
            "embedding": settings.embedding_model,
        }

    return application


app = create_app()
