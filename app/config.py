"""Application settings — Railway production + local dev."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration for the RAG service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "company-rag"
    app_env: str = "development"
    app_debug: bool = True
    api_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    phase: int = 4
    disable_docs: bool = False
    auto_migrate: bool = True

    # Auth
    auth_enabled: bool = False
    api_keys_json: str = ""
    api_key_admin: str = "dev-admin-key"
    api_key_user: str = "dev-user-key"
    bootstrap_admin_key: str = ""
    bootstrap_admin_email: str = "admin@platform.local"
    bootstrap_admin_name: str = "Platform Admin"
    bootstrap_admin_password: str = "change-me"

    # Rate limits
    rate_limit_enabled: bool = True
    rate_limit_query_per_minute: int = 30
    rate_limit_ingest_per_minute: int = 10
    max_upload_bytes: int = 10 * 1024 * 1024
    max_question_chars: int = 2000

    # CORS
    cors_origins: str = "*"

    # Database (Railway Postgres or local SQLite)
    # Railway: postgresql://...  Local default: sqlite
    database_url: str = "sqlite:///./data/company_rag.db"

    # S3 / Railway bucket (optional local filesystem fallback)
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = ""
    s3_region: str = "auto"
    local_storage_dir: str = "./data/uploads"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_site_url: str = "http://localhost"
    openrouter_app_name: str = "company-rag"
    llm_temperature: float = 0.0
    openrouter_timeout_seconds: float = 60.0
    openrouter_max_retries: int = 2

    # HF embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_dimension: int = 384

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index_name: str = "company-rag"
    pinecone_namespace: str = "default"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_timeout_seconds: float = 30.0

    # RAG
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k: int = 5
    max_chunks_per_ingest: int = 50
    max_context_chars: int = 4000

    # Speed
    warmup_embeddings: bool = True
    include_timings: bool = True
    embed_cache_enabled: bool = True
    answer_cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    cache_max_size: int = 2048
    retrieve_top_k: int = 10
    return_top_n: int = 3
    min_retrieval_score: float = 0.15
    max_chars_per_chunk: int = 800
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_skip_if_top_score: bool = True
    rerank_skip_score: float = 0.85
    streaming_enabled: bool = True

    # Product mode (API platform for other companies)
    product_mode: str = "api_platform"  # api_platform | full_demo
    enable_chat_ui: bool = False
    enable_dev_ui: bool = False
    enable_admin_ui: bool = True
    allow_tenant_model_override: bool = True
    # Public URL for Integration card (Railway custom domain)
    public_base_url: str = ""

    # Logging / UI
    log_format: str = "text"
    log_level: str = "INFO"
    ui_enabled: bool = True

    @field_validator("app_env")
    @classmethod
    def normalize_env(cls, v: str) -> str:
        return (v or "development").strip().lower()

    @field_validator("database_url")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        url = (v or "").strip()
        if url.startswith("postgres://"):
            return "postgresql://" + url[len("postgres://") :]
        return url

    @model_validator(mode="after")
    def apply_storage_env_aliases(self) -> Settings:
        """Map Railway Bucket / AWS standard env names → S3_* settings.

        Railway Storage Buckets inject:
          BUCKET, ACCESS_KEY_ID, SECRET_ACCESS_KEY, ENDPOINT, REGION
        AWS-style:
          AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL, AWS_REGION
        """

        def first(*names: str) -> str:
            for n in names:
                v = (os.environ.get(n) or "").strip()
                if v:
                    return v
            return ""

        if not self.s3_bucket_name.strip():
            self.s3_bucket_name = first(
                "S3_BUCKET_NAME", "BUCKET", "AWS_S3_BUCKET", "BUCKET_NAME"
            )
        if not self.s3_access_key_id.strip():
            self.s3_access_key_id = first(
                "S3_ACCESS_KEY_ID", "ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"
            )
        if not self.s3_secret_access_key.strip():
            self.s3_secret_access_key = first(
                "S3_SECRET_ACCESS_KEY", "SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"
            )
        if not self.s3_endpoint_url.strip():
            self.s3_endpoint_url = first(
                "S3_ENDPOINT_URL",
                "ENDPOINT",
                "AWS_ENDPOINT_URL",
                "AWS_ENDPOINT",
                "S3_ENDPOINT",
            )
        if not self.s3_region.strip() or self.s3_region.strip() == "auto":
            region = first("S3_REGION", "REGION", "AWS_REGION")
            if region:
                self.s3_region = region
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def is_pinecone_configured(self) -> bool:
        return bool(self.pinecone_api_key.strip())

    @property
    def is_database_configured(self) -> bool:
        return bool(self.database_url.strip())

    @property
    def is_s3_configured(self) -> bool:
        return bool(
            self.s3_bucket_name.strip()
            and self.s3_access_key_id.strip()
            and self.s3_secret_access_key.strip()
        )

    @property
    def storage_backend(self) -> str:
        return "s3" if self.is_s3_configured else "local"

    @property
    def sqlalchemy_database_url(self) -> str:
        """Normalize DB URL for SQLAlchemy + psycopg3 (Railway Postgres)."""
        url = (self.database_url or "").strip()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        # requirements use psycopg v3 — force the dialect so connect works on Railway
        if url.startswith("postgresql://") and "+psycopg" not in url and "+asyncpg" not in url:
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    @property
    def docs_url(self) -> str | None:
        if self.disable_docs or (self.is_production and not self.app_debug):
            return None
        return "/docs"

    @property
    def redoc_url(self) -> str | None:
        if self.disable_docs or (self.is_production and not self.app_debug):
            return None
        return "/redoc"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @staticmethod
    def clean_secret(value: str | None) -> str:
        """Strip whitespace and optional surrounding quotes from secrets."""
        s = (value or "").strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in {'"', "'"}:
            s = s[1:-1].strip()
        return s

    def parse_api_keys(self) -> list[dict[str, str]]:
        """Build env bootstrap key list (admin + optional user / JSON keys)."""
        keys: list[dict[str, str]] = []
        raw_json = self.clean_secret(self.api_keys_json)
        if raw_json:
            try:
                data: Any = json.loads(raw_json)
                items = data if isinstance(data, list) else data.get("keys", [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    k = self.clean_secret(str(item.get("key") or ""))
                    if not k:
                        continue
                    role = str(item.get("role") or "user").strip().lower()
                    # Treat platform_admin / admin the same for env keys
                    if role in {"platform_admin", "platform-admin", "superadmin"}:
                        role = "admin"
                    keys.append(
                        {
                            "key": k,
                            "role": role,
                            "name": str(item.get("name") or "client").strip() or "client",
                        }
                    )
            except json.JSONDecodeError:
                pass
        admin = self.clean_secret(self.bootstrap_admin_key) or self.clean_secret(
            self.api_key_admin
        )
        if admin:
            keys.append({"key": admin, "role": "admin", "name": "admin"})
        user = self.clean_secret(self.api_key_user)
        if user:
            keys.append({"key": user, "role": "user", "name": "user"})
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for item in keys:
            if item["key"] in seen:
                continue
            seen.add(item["key"])
            unique.append(item)
        return unique

    def validate_production(self) -> None:
        if not self.is_production:
            return
        errors: list[str] = []
        if self.auth_enabled and not self.parse_api_keys():
            errors.append("AUTH_ENABLED but no API keys configured")
        if not self.is_openrouter_configured:
            errors.append("OPENROUTER_API_KEY required in production")
        if not self.is_pinecone_configured:
            errors.append("PINECONE_API_KEY required in production")
        if not self.is_database_configured:
            errors.append("DATABASE_URL required in production")
        if errors:
            raise RuntimeError("Production config invalid: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
