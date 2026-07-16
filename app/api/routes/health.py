"""Health and readiness routes (public)."""

from fastapi import APIRouter

from app.config import settings
from app.db.session import check_db, db_error_hint
from app.models.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        phase=settings.phase,
        app_name=settings.app_name,
        detail="alive",
    )


@router.get("/ready", response_model=ReadyResponse)
def ready() -> ReadyResponse:
    or_ok = settings.is_openrouter_configured
    pc_ok = settings.is_pinecone_configured
    db_ok = check_db()
    storage_ok = False
    try:
        from app.storage.s3_client import get_storage

        storage_ok = get_storage().health_check()
    except Exception:  # noqa: BLE001
        storage_ok = False

    missing = []
    if not or_ok:
        missing.append("OpenRouter")
    if not pc_ok:
        missing.append("Pinecone")
    if not db_ok:
        missing.append("Database")
    if not storage_ok:
        missing.append("Storage")

    db_hint = None if db_ok else db_error_hint()

    # core ready for RAG needs OR + Pinecone + DB; storage required for uploads
    if or_ok and pc_ok and db_ok:
        status = "ready" if not missing else "degraded"
        if missing == ["Storage"]:
            status = "ready"  # chat works; uploads need storage
            detail = "RAG ready; storage check failed — uploads may use local path"
        else:
            detail = "OpenRouter + Pinecone + Database OK"
            if storage_ok:
                detail += f"; storage={settings.storage_backend}"
    else:
        status = "not_ready"
        detail = "Missing: " + ", ".join(missing) if missing else "not ready"
        if db_hint:
            detail = f"{detail}. DB: {db_hint}"

    return ReadyResponse(
        status=status if status != "degraded" else "ready",
        phase=settings.phase,
        app_name=settings.app_name,
        auth_enabled=settings.auth_enabled,
        openrouter_configured=or_ok,
        pinecone_configured=pc_ok,
        embedding_model=settings.embedding_model,
        index_name=settings.pinecone_index_name,
        detail=detail,
        speed_features={
            "warmup": settings.warmup_embeddings,
            "embed_cache": settings.embed_cache_enabled,
            "answer_cache": settings.answer_cache_enabled,
            "rerank": settings.rerank_enabled,
            "streaming": settings.streaming_enabled,
            "database": db_ok,
            "database_hint": db_hint,
            "storage": storage_ok,
            "storage_backend": settings.storage_backend,
            "s3_configured": settings.is_s3_configured,
            "s3_bucket": settings.s3_bucket_name or None,
            "s3_endpoint_set": bool(settings.s3_endpoint_url.strip()),
            "retrieve_top_k": settings.retrieve_top_k,
            "return_top_n": settings.return_top_n,
            "db_dialect": (settings.sqlalchemy_database_url.split("://")[0]
                           if settings.database_url else None),
        },
    )
