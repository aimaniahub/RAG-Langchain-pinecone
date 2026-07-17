"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.logging import get_logger
from app.db.base import Base

logger = get_logger("db")

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = settings.sqlalchemy_database_url
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            # Ensure parent dir exists for local sqlite files
            if ":///" in url:
                from pathlib import Path

                raw_path = url.split("///", 1)[1]
                if raw_path and raw_path != ":memory:":
                    Path(raw_path).expanduser().resolve().parent.mkdir(
                        parents=True, exist_ok=True
                    )
        engine_kwargs: dict = {
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        if url.startswith("sqlite"):
            # Allow nested requests (admin API + open session) without pool deadlocks
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 10
        else:
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 10
        _engine = create_engine(url, **engine_kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
        # Log scheme only — never log credentials
        scheme = url.split("://", 1)[0] if "://" in url else "unknown"
        logger.info("DB engine created dialect=%s", scheme)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def init_db() -> None:
    """Create tables + additive column migrations (SQLite / Postgres)."""
    engine = get_engine()
    # import models so metadata is populated
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_tenant_rag_columns(engine)
    logger.info("DB tables ensured")


def _ensure_tenant_rag_columns(engine) -> None:
    """Add per-company RAG config columns if missing (no full Alembic required)."""
    from sqlalchemy import inspect, text

    try:
        insp = inspect(engine)
        if "tenants" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("tenants")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("schema inspect failed: %s", exc)
        return

    # SQLAlchemy type → portable SQL type for ADD COLUMN
    needed: dict[str, str] = {
        "system_prompt": "TEXT",
        "top_k": "INTEGER",
        "return_top_n": "INTEGER",
        "max_context_chars": "INTEGER",
        "max_question_chars": "INTEGER",
        "max_chars_per_chunk": "INTEGER",
        "temperature": "FLOAT",
        "min_retrieval_score": "FLOAT",
        "rerank_enabled": "INTEGER",
        "answer_cache_enabled": "INTEGER",
        "no_context_message": "TEXT",
        "llm_api_key": "TEXT",
        "llm_base_url": "TEXT",
    }
    missing = [c for c in needed if c not in existing]
    if not missing:
        return
    with engine.begin() as conn:
        for col in missing:
            ddl = f"ALTER TABLE tenants ADD COLUMN {col} {needed[col]}"
            try:
                conn.execute(text(ddl))
                logger.info("schema: added tenants.%s", col)
            except Exception as exc:  # noqa: BLE001
                logger.warning("schema add %s failed: %s", col, exc)


def check_db() -> bool:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        # Never log full URL (may contain password)
        msg = str(exc).split("\n")[0][:240]
        logger.warning("DB check failed: %s", msg)
        return False


def db_error_hint() -> str | None:
    """Short, safe reason for admin/ready when DB is down (no credentials)."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:  # noqa: BLE001
        raw = str(exc)
        low = raw.lower()
        if "psycopg2" in low or "no module named 'psycopg2'" in low:
            return "Postgres driver: use postgresql+psycopg (psycopg3). Redeploy latest app."
        if "could not translate host name" in low or "name or service not known" in low:
            return "Cannot resolve DB host. Use Railway private URL and same project as Postgres."
        if "connection refused" in low or "timeout" in low:
            return "DB connection refused/timeout. Check DATABASE_URL and that Postgres is running."
        if "password authentication failed" in low:
            return "DB password rejected. Re-copy DATABASE_URL from the Postgres service."
        if "ssl" in low:
            return "SSL/DB connection error. Check Railway Postgres URL."
        return raw.split("\n")[0][:180]


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
