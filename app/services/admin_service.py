"""Enterprise admin orchestration: setup status, users, tenants, keys, guidance."""

from __future__ import annotations

import hashlib
import re
import secrets  # noqa: F401 — used for password fallbacks
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.core.security import hash_api_key, key_prefix
from app.db.models import (
    ApiKey,
    Document,
    ModelCatalog,
    Tenant,
    TenantMember,
    UsageEvent,
    User,
)
from app.db.session import check_db
from app.storage.s3_client import get_storage


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return (s or "tenant")[:64]


def _hash_password(password: str) -> str:
    return hashlib.sha256(f"rag:{password}".encode()).hexdigest()


class AdminService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ─── Setup / guidance ───────────────────────────────────────────
    def setup_status(self) -> dict:
        """Single source of truth for admin onboarding checklist."""
        db_ok = check_db()
        storage_ok = False
        try:
            storage_ok = get_storage().health_check()
        except Exception:  # noqa: BLE001
            storage_ok = False

        tenants = self.db.query(func.count(Tenant.id)).scalar() or 0
        active_tenants = (
            self.db.query(func.count(Tenant.id)).filter(Tenant.status == "active").scalar() or 0
        )
        keys = (
            self.db.query(func.count(ApiKey.id)).filter(ApiKey.status == "active").scalar() or 0
        )
        tenant_keys = (
            self.db.query(func.count(ApiKey.id))
            .filter(ApiKey.status == "active", ApiKey.role == "tenant")
            .scalar()
            or 0
        )
        docs = self.db.query(func.count(Document.id)).scalar() or 0
        ready_docs = (
            self.db.query(func.count(Document.id)).filter(Document.status == "ready").scalar()
            or 0
        )
        users = self.db.query(func.count(User.id)).scalar() or 0
        queries = (
            self.db.query(func.count(UsageEvent.id))
            .filter(UsageEvent.event_type == "query")
            .scalar()
            or 0
        )
        models = self.db.query(func.count(ModelCatalog.id)).scalar() or 0

        steps = [
            {
                "id": "database",
                "title": "1. Database connected",
                "done": db_ok,
                "hint": "Set DATABASE_URL to Postgres on Railway, or use local SQLite.",
            },
            {
                "id": "integrations",
                "title": "2. OpenRouter + Pinecone keys",
                "done": settings.is_openrouter_configured and settings.is_pinecone_configured,
                "hint": "Set OPENROUTER_API_KEY and PINECONE_API_KEY in env.",
            },
            {
                "id": "storage",
                "title": "3. File storage ready",
                "done": storage_ok,
                "hint": "Local ./data/uploads works; for Railway set S3_* vars.",
            },
            {
                "id": "tenant",
                "title": "4. Create a client company (tenant)",
                "done": active_tenants > 0,
                "hint": "Admin → Tenants → Create. Each company gets its own Pinecone namespace.",
            },
            {
                "id": "api_key",
                "title": "5. Issue an API key for that company",
                "done": tenant_keys > 0,
                "hint": "Admin → API Keys → select tenant → Issue key. Copy the secret once.",
            },
            {
                "id": "documents",
                "title": "6. Upload knowledge docs for the company",
                "done": ready_docs > 0,
                "hint": "Admin → Documents → choose tenant → upload PDF/MD/TXT (auto-embeds).",
            },
            {
                "id": "query",
                "title": "7. Client calls POST /api/v1/query with the key",
                "done": queries > 0,
                "hint": "Other company backends use X-API-Key header. No need for our chat UI.",
            },
        ]
        done_count = sum(1 for s in steps if s["done"])
        next_step = next((s for s in steps if not s["done"]), None)

        return {
            "setup_complete": done_count == len(steps),
            "progress": {"done": done_count, "total": len(steps)},
            "next_step": next_step,
            "steps": steps,
            "counts": {
                "tenants": int(tenants),
                "active_tenants": int(active_tenants),
                "api_keys_active": int(keys),
                "tenant_keys_active": int(tenant_keys),
                "documents": int(docs),
                "documents_ready": int(ready_docs),
                "users": int(users),
                "queries": int(queries),
                "models": int(models),
            },
            "integrations": {
                "database": db_ok,
                "database_url_scheme": (settings.database_url or "").split(":")[0],
                "storage": storage_ok,
                "storage_backend": settings.storage_backend,
                "openrouter": settings.is_openrouter_configured,
                "pinecone": settings.is_pinecone_configured,
                "auth_enabled": settings.auth_enabled,
            },
            "how_it_works": [
                "This product is a RAG API platform — other companies call your HTTP endpoints.",
                "Create a Tenant per client company (isolated Pinecone namespace).",
                "Issue an API key with scopes (query / ingest / docs).",
                "Upload documents assigned to that tenant (auto chunk + embed to Pinecone).",
                "Give the company only: base URL + API key + OpenAPI (/docs).",
                "They build their own UI; you operate tenants, keys, models, and usage here.",
            ],
            "partner_endpoints": {
                "query": "POST /api/v1/query",
                "ingest_text": "POST /api/v1/ingest",
                "ingest_file": "POST /api/v1/ingest/file",
                "documents": "GET|POST /api/v1/documents",
                "auth_header": "X-API-Key: <key>",
            },
            "public_base_url": (settings.public_base_url or "").rstrip("/"),
            "api_prefix": settings.api_prefix.rstrip("/") or "/api/v1",
        }

    def list_tenants_enriched(self) -> list[dict]:
        """Tenants with live counts for Companies list."""
        tenants = self.list_tenants()
        out: list[dict] = []
        for t in tenants:
            keys = (
                self.db.query(func.count(ApiKey.id))
                .filter(ApiKey.tenant_id == t.id, ApiKey.status == "active")
                .scalar()
                or 0
            )
            docs = (
                self.db.query(func.count(Document.id))
                .filter(Document.tenant_id == t.id)
                .scalar()
                or 0
            )
            ready = (
                self.db.query(func.count(Document.id))
                .filter(Document.tenant_id == t.id, Document.status == "ready")
                .scalar()
                or 0
            )
            queries = (
                self.db.query(func.count(UsageEvent.id))
                .filter(UsageEvent.tenant_id == t.id, UsageEvent.event_type == "query")
                .scalar()
                or 0
            )
            out.append(
                {
                    "tenant": t,
                    "keys_active": int(keys),
                    "documents": int(docs),
                    "documents_ready": int(ready),
                    "query_count": int(queries),
                }
            )
        return out

    def remove_membership(self, membership_id: str) -> None:
        m = self.db.get(TenantMember, membership_id)
        if not m:
            raise AppError("Membership not found")
        self.db.delete(m)
        self.db.commit()

    def set_user_status(self, user_id: str, status: str) -> User:
        u = self.db.get(User, user_id)
        if not u:
            raise AppError("User not found")
        if status not in {"active", "disabled"}:
            raise AppError("Invalid status")
        u.status = status
        u.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(u)
        return u

    def usage_events(self, limit: int = 50, tenant_id: str | None = None) -> list[UsageEvent]:
        q = self.db.query(UsageEvent).order_by(UsageEvent.created_at.desc())
        if tenant_id:
            q = q.filter(UsageEvent.tenant_id == tenant_id)
        return q.limit(limit).all()

    def seed_defaults(self) -> None:
        """Idempotent: models + optional bootstrap operator user."""
        self.ensure_default_models()
        email = (settings.bootstrap_admin_email or "admin@platform.local").strip().lower()
        existing = self.db.query(User).filter(User.email == email).first()
        if not existing:
            self.db.add(
                User(
                    email=email,
                    full_name=settings.bootstrap_admin_name or "Platform Admin",
                    role="platform_admin",
                    status="active",
                    password_hash=_hash_password(
                        settings.bootstrap_admin_password or "change-me"
                    ),
                )
            )
            self.db.commit()

    # ─── Users ──────────────────────────────────────────────────────
    def list_users(self) -> list[User]:
        return self.db.query(User).order_by(User.created_at.desc()).all()

    def create_user(
        self,
        email: str,
        full_name: str,
        role: str = "operator",
        password: str | None = None,
    ) -> User:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise AppError("Valid email is required")
        if self.db.query(User).filter(User.email == email).first():
            raise AppError("User email already exists")
        if role not in {"platform_admin", "operator", "viewer"}:
            raise AppError("Invalid role")
        u = User(
            email=email,
            full_name=(full_name or email).strip()[:256],
            role=role,
            status="active",
            password_hash=_hash_password(password or secrets.token_urlsafe(12)),
        )
        self.db.add(u)
        self.db.commit()
        self.db.refresh(u)
        return u

    def assign_user_to_tenant(
        self, user_id: str, tenant_id: str, role: str = "tenant_member"
    ) -> TenantMember:
        user = self.db.get(User, user_id)
        tenant = self.db.get(Tenant, tenant_id)
        if not user:
            raise AppError("User not found")
        if not tenant:
            raise AppError("Tenant not found")
        if role not in {"tenant_admin", "tenant_member"}:
            raise AppError("Invalid membership role")
        existing = (
            self.db.query(TenantMember)
            .filter(TenantMember.user_id == user_id, TenantMember.tenant_id == tenant_id)
            .first()
        )
        if existing:
            existing.role = role
            self.db.commit()
            self.db.refresh(existing)
            return existing
        m = TenantMember(user_id=user_id, tenant_id=tenant_id, role=role)
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return m

    def list_memberships(self, tenant_id: str | None = None) -> list[TenantMember]:
        q = self.db.query(TenantMember)
        if tenant_id:
            q = q.filter(TenantMember.tenant_id == tenant_id)
        return q.order_by(TenantMember.created_at.desc()).all()

    # ─── Tenants ────────────────────────────────────────────────────
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
            raise AppError("Company name is required")
        base = _slugify(slug or name)
        slug_final = base
        i = 1
        while self.db.query(Tenant).filter(Tenant.slug == slug_final).first():
            slug_final = f"{base}-{i}"
            i += 1
        # Unique Pinecone namespace — never "default"; never shared across companies
        ns_base = ("co_" + slug_final.replace("-", "_"))[:60]
        ns = ns_base
        j = 1
        while self.db.query(Tenant).filter(Tenant.pinecone_namespace == ns).first():
            ns = f"{ns_base}_{j}"[:64]
            j += 1
        if ns in {"default", "platform", ""}:
            ns = f"co_{secrets.token_hex(4)}"
        t = Tenant(
            name=name,
            slug=slug_final,
            status="active",
            pinecone_namespace=ns,
            default_model=default_model or settings.openrouter_model,
            rate_limit_rpm=rate_limit_rpm or 60,
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
        str_fields = ("name", "status", "default_model", "notes", "system_prompt", "no_context_message")
        for k in str_fields:
            if k not in fields:
                continue
            val = fields[k]
            if k in {"system_prompt", "no_context_message", "notes", "default_model"}:
                # allow explicit null/empty to clear override
                if val is None or (isinstance(val, str) and not val.strip()):
                    setattr(t, k, None if k != "name" else t.name)
                else:
                    setattr(t, k, str(val).strip() if k != "system_prompt" else str(val))
            elif val is not None:
                setattr(t, k, val)

        int_fields = (
            "rate_limit_rpm",
            "top_k",
            "return_top_n",
            "max_context_chars",
            "max_question_chars",
            "max_chars_per_chunk",
        )
        for k in int_fields:
            if k not in fields:
                continue
            val = fields[k]
            if val is None or val == "":
                if k == "rate_limit_rpm":
                    continue
                setattr(t, k, None)
            else:
                iv = int(val)
                if k == "top_k" and not 1 <= iv <= 50:
                    raise AppError("top_k must be 1–50")
                if k == "return_top_n" and not 1 <= iv <= 20:
                    raise AppError("return_top_n must be 1–20")
                if k == "rate_limit_rpm" and iv < 1:
                    raise AppError("rate_limit_rpm must be ≥ 1")
                setattr(t, k, iv)

        float_fields = ("temperature", "min_retrieval_score")
        for k in float_fields:
            if k not in fields:
                continue
            val = fields[k]
            if val is None or val == "":
                setattr(t, k, None)
            else:
                fv = float(val)
                if k == "temperature" and not 0.0 <= fv <= 2.0:
                    raise AppError("temperature must be 0–2")
                if k == "min_retrieval_score" and not 0.0 <= fv <= 1.0:
                    raise AppError("min_retrieval_score must be 0–1")
                setattr(t, k, fv)

        bool_int_fields = ("rerank_enabled", "answer_cache_enabled")
        for k in bool_int_fields:
            if k not in fields:
                continue
            val = fields[k]
            if val is None:
                setattr(t, k, None)
            else:
                setattr(t, k, 1 if bool(val) else 0)

        t.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(t)
        return t

    def tenant_detail(self, tenant_id: str) -> dict:
        t = self.get_tenant(tenant_id)
        if not t:
            raise AppError("Tenant not found")
        keys = (
            self.db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant_id)
            .order_by(ApiKey.created_at.desc())
            .all()
        )
        docs = (
            self.db.query(Document)
            .filter(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc())
            .all()
        )
        members = (
            self.db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id).all()
        )
        qcount = (
            self.db.query(func.count(UsageEvent.id))
            .filter(UsageEvent.tenant_id == tenant_id, UsageEvent.event_type == "query")
            .scalar()
            or 0
        )
        return {
            "tenant": t,
            "keys": keys,
            "documents": docs,
            "members": members,
            "query_count": int(qcount),
            "isolation": {
                "tenant_id": t.id,
                "slug": t.slug,
                "pinecone_namespace": t.pinecone_namespace,
                "s3_prefix": f"companies/{t.slug}/documents/",
                "rule": "Only this company's API key may query these vectors",
            },
        }

    def reindex_tenant_documents(self, tenant_id: str) -> dict:
        """Re-embed all company docs into the correct Pinecone namespace (isolation repair)."""
        from app.services.document_service import DocumentService

        t = self.get_tenant(tenant_id)
        if not t:
            raise AppError("Tenant not found")
        docs = (
            self.db.query(Document)
            .filter(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.asc())
            .all()
        )
        svc = DocumentService(self.db)
        ok, failed = [], []
        for d in docs:
            # force namespace sync
            d.namespace = t.pinecone_namespace
            self.db.commit()
            try:
                svc.process_document(d.id)
                ok.append(d.id)
            except Exception as exc:  # noqa: BLE001
                failed.append({"id": d.id, "filename": d.filename, "error": str(exc)[:200]})
        return {
            "tenant_id": tenant_id,
            "namespace": t.pinecone_namespace,
            "total": len(docs),
            "reindexed": len(ok),
            "failed": failed,
            "ok_ids": ok,
        }

    # ─── Keys ───────────────────────────────────────────────────────
    def create_key(
        self,
        *,
        name: str,
        tenant_id: str | None = None,
        scopes: list[str] | None = None,
        role: str = "tenant",
        created_by_user_id: str | None = None,
    ) -> tuple[ApiKey, str]:
        if role == "tenant" and not tenant_id:
            raise AppError("Select a tenant for company API keys")
        if tenant_id:
            t = self.get_tenant(tenant_id)
            if not t:
                raise AppError("Tenant not found")
            if t.status != "active":
                raise AppError("Tenant is disabled — enable it before issuing keys")

        raw = "rag_live_" + secrets.token_urlsafe(32)
        scopes = scopes or ["query:read"]
        if role == "platform_admin":
            scopes = list(
                set(scopes)
                | {"platform:admin", "query:read", "ingest:write", "docs:read"}
            )
        else:
            # tenant keys should not get platform:admin
            scopes = [s for s in scopes if s != "platform:admin"]

        row = ApiKey(
            tenant_id=tenant_id,
            name=(name or "api-key").strip()[:128],
            key_prefix=key_prefix(raw),
            key_hash=hash_api_key(raw),
            scopes=",".join(sorted(set(scopes))),
            role=role,
            status="active",
            created_by_user_id=created_by_user_id,
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
            name=f"{old.name} (rotated)",
            tenant_id=old.tenant_id,
            scopes=[s for s in (old.scopes or "").split(",") if s],
            role=old.role,
        )

    # ─── Models ─────────────────────────────────────────────────────
    def ensure_default_models(self) -> None:
        if self.db.query(ModelCatalog).count() > 0:
            return
        for mid, label, is_def in [
            ("openai/gpt-4o-mini", "GPT-4o Mini (recommended)", 1),
            ("openai/gpt-4o", "GPT-4o", 0),
            ("google/gemini-2.0-flash-001", "Gemini 2.0 Flash", 0),
            ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", 0),
        ]:
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

    def list_models(self) -> list[ModelCatalog]:
        self.ensure_default_models()
        return self.db.query(ModelCatalog).order_by(ModelCatalog.label.asc()).all()

    def set_default_model(self, model_id: str) -> ModelCatalog:
        self.ensure_default_models()
        found = None
        for r in self.db.query(ModelCatalog).all():
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

    # ─── Guided onboard (one call creates tenant + key) ─────────────
    def onboard_company(
        self,
        company_name: str,
        key_name: str = "production",
        scopes: list[str] | None = None,
        default_model: str | None = None,
    ) -> dict:
        """Enterprise shortcut: create tenant + first API key in one step."""
        t = self.create_tenant(name=company_name, default_model=default_model)
        scopes = scopes or ["query:read", "ingest:write", "docs:read"]
        row, raw = self.create_key(
            name=key_name,
            tenant_id=t.id,
            scopes=scopes,
            role="tenant",
        )
        return {
            "tenant": t,
            "key": row,
            "api_key_plaintext": raw,
            "next_steps": [
                f"Upload documents for tenant {t.id} (Documents tab or POST /api/v1/admin/tenants/{t.id}/documents).",
                "Give the client company: base URL + the API key below (only shown once).",
                "Client calls POST /api/v1/query with header X-API-Key.",
                f"Their Pinecone namespace is isolated: {t.pinecone_namespace}",
            ],
        }
