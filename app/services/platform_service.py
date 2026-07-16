"""Tenant, API key, and model catalog management."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.core.security import hash_api_key, key_prefix
from app.db.models import ApiKey, ModelCatalog, Tenant, UsageEvent


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return (s or "tenant")[:64]


class PlatformService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- tenants ----
    def create_tenant(
        self,
        name: str,
        slug: str | None = None,
        default_model: str | None = None,
        rate_limit_rpm: int = 60,
        notes: str | None = None,
    ) -> Tenant:
        name = (name or "").strip()
        if not name:
            raise AppError("Tenant name is required")
        base = _slugify(slug or name)
        slug_final = base
        i = 1
        while self.db.query(Tenant).filter(Tenant.slug == slug_final).first():
            slug_final = f"{base}-{i}"
            i += 1
        ns = slug_final.replace("-", "_")[:64]
        t = Tenant(
            name=name,
            slug=slug_final,
            status="active",
            pinecone_namespace=ns,
            default_model=default_model or settings.openrouter_model,
            rate_limit_rpm=rate_limit_rpm,
            notes=notes,
        )
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def list_tenants(self) -> list[Tenant]:
        return self.db.query(Tenant).order_by(Tenant.created_at.desc()).all()

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self.db.get(Tenant, tenant_id)

    def update_tenant(self, tenant_id: str, **fields) -> Tenant:
        t = self.get_tenant(tenant_id)
        if not t:
            raise AppError("Tenant not found")
        for k, v in fields.items():
            if v is None:
                continue
            if k in {"name", "status", "default_model", "notes"} and hasattr(t, k):
                setattr(t, k, v)
            if k == "rate_limit_rpm" and v is not None:
                t.rate_limit_rpm = int(v)
        t.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(t)
        return t

    # ---- keys ----
    def create_key(
        self,
        *,
        name: str,
        tenant_id: str | None = None,
        scopes: list[str] | None = None,
        role: str = "tenant",
    ) -> tuple[ApiKey, str]:
        """Returns (row, plaintext_key). Plaintext shown only once."""
        if role == "tenant" and not tenant_id:
            raise AppError("tenant_id required for tenant keys")
        if tenant_id:
            t = self.get_tenant(tenant_id)
            if not t:
                raise AppError("Tenant not found")
            if t.status != "active":
                raise AppError("Tenant is disabled")

        raw = "rag_live_" + secrets.token_urlsafe(32)
        scopes = scopes or ["query:read"]
        if role == "platform_admin":
            scopes = list(set(scopes) | {"platform:admin", "query:read", "ingest:write", "docs:read"})

        row = ApiKey(
            tenant_id=tenant_id,
            name=(name or "key").strip()[:128],
            key_prefix=key_prefix(raw),
            key_hash=hash_api_key(raw),
            scopes=",".join(sorted(set(scopes))),
            role=role,
            status="active",
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, raw

    def list_keys(self, tenant_id: str | None = None) -> list[ApiKey]:
        q = self.db.query(ApiKey).order_by(ApiKey.created_at.desc())
        if tenant_id:
            q = q.filter(ApiKey.tenant_id == tenant_id)
        return q.all()

    def revoke_key(self, key_id: str) -> ApiKey:
        row = self.db.get(ApiKey, key_id)
        if not row:
            raise AppError("API key not found")
        row.status = "revoked"
        self.db.commit()
        self.db.refresh(row)
        return row

    def rotate_key(self, key_id: str) -> tuple[ApiKey, str]:
        old = self.db.get(ApiKey, key_id)
        if not old:
            raise AppError("API key not found")
        old.status = "revoked"
        self.db.commit()
        return self.create_key(
            name=old.name + " (rotated)",
            tenant_id=old.tenant_id,
            scopes=[s for s in old.scopes.split(",") if s],
            role=old.role,
        )

    # ---- models ----
    def ensure_default_models(self) -> None:
        if self.db.query(ModelCatalog).count() > 0:
            return
        defaults = [
            ("openai/gpt-4o-mini", "GPT-4o Mini", 1),
            ("openai/gpt-4o", "GPT-4o", 0),
            ("google/gemini-2.0-flash-001", "Gemini 2.0 Flash", 0),
            ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", 0),
        ]
        for mid, label, is_def in defaults:
            self.db.add(
                ModelCatalog(
                    provider="openrouter",
                    model_id=mid,
                    label=label,
                    enabled=1,
                    is_default=is_def,
                )
            )
        self.db.commit()

    def list_models(self, enabled_only: bool = False) -> list[ModelCatalog]:
        self.ensure_default_models()
        q = self.db.query(ModelCatalog).order_by(ModelCatalog.label.asc())
        if enabled_only:
            q = q.filter(ModelCatalog.enabled == 1)
        return q.all()

    def set_default_model(self, model_id: str) -> ModelCatalog:
        self.ensure_default_models()
        rows = self.db.query(ModelCatalog).all()
        found = None
        for r in rows:
            r.is_default = 0
            if r.model_id == model_id:
                r.is_default = 1
                r.enabled = 1
                found = r
        if not found:
            found = ModelCatalog(
                provider="openrouter",
                model_id=model_id,
                label=model_id,
                enabled=1,
                is_default=1,
            )
            self.db.add(found)
        self.db.commit()
        self.db.refresh(found)
        return found

    def set_model_enabled(self, model_id: str, enabled: bool) -> ModelCatalog:
        self.ensure_default_models()
        row = self.db.query(ModelCatalog).filter(ModelCatalog.model_id == model_id).first()
        if not row:
            raise AppError("Model not found")
        row.enabled = 1 if enabled else 0
        self.db.commit()
        self.db.refresh(row)
        return row

    def usage_by_tenant(self) -> list[dict]:
        rows = (
            self.db.query(UsageEvent.tenant_id, UsageEvent.event_type)
            .all()
        )
        # simple aggregate in python
        agg: dict[str, dict] = {}
        for tid, et in rows:
            key = tid or "none"
            if key not in agg:
                agg[key] = {"tenant_id": tid, "query": 0, "ingest": 0}
            if et == "query":
                agg[key]["query"] += 1
            elif et == "ingest":
                agg[key]["ingest"] += 1
        return list(agg.values())
