"""Unified enterprise Admin API — setup, users, tenants, keys, models, docs, usage."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.core.security import Principal, require_platform_admin
from app.db.models import User
from app.db.session import get_db
from app.services.admin_service import AdminService
from app.services.document_service import DocumentService

router = APIRouter(tags=["admin-console"])


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.message)
    return HTTPException(status_code=500, detail=str(exc)[:300])


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "status": u.status,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _tenant_dict(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "status": t.status,
        "pinecone_namespace": t.pinecone_namespace,
        "default_model": t.default_model,
        "rate_limit_rpm": t.rate_limit_rpm,
        "notes": t.notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _key_dict(k) -> dict:
    return {
        "id": k.id,
        "tenant_id": k.tenant_id,
        "name": k.name,
        "key_prefix": k.key_prefix,
        "scopes": [s for s in (k.scopes or "").split(",") if s],
        "role": k.role,
        "status": k.status,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


def _doc_dict(d) -> dict:
    return {
        "id": d.id,
        "tenant_id": d.tenant_id,
        "filename": d.filename,
        "status": d.status,
        "namespace": d.namespace,
        "chunk_count": d.chunk_count,
        "vector_count": d.vector_count,
        "size_bytes": d.size_bytes,
        "error": d.error,
        "uploaded_by": d.uploaded_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


# ═══════════════════════════════════════════════════════════════════
# SETUP / DASHBOARD (guidance)
# ═══════════════════════════════════════════════════════════════════


@router.get("/admin/setup")
def setup_status(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    """Onboarding checklist + how the platform works."""
    _ = principal
    return AdminService(db).setup_status()


@router.get("/admin/dashboard")
def dashboard(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    """Full admin home: setup + counts + integrations."""
    _ = principal
    svc = AdminService(db)
    status = svc.setup_status()
    return {
        "status": "ok",
        "actor": principal.key_name,
        "setup": status,
        "product": {
            "mode": settings.product_mode,
            "message": "API platform for client companies — not an end-user chat app.",
        },
    }


# ═══════════════════════════════════════════════════════════════════
# ONE-CLICK ONBOARD
# ═══════════════════════════════════════════════════════════════════


class OnboardBody(BaseModel):
    company_name: str = Field(..., min_length=1)
    key_name: str = "production"
    default_model: str | None = None
    scopes: list[str] = Field(
        default_factory=lambda: ["query:read", "ingest:write", "docs:read"]
    )


@router.post("/admin/onboard")
def onboard_company(
    body: OnboardBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    """Create company + first API key in one step (recommended)."""
    _ = principal
    try:
        result = AdminService(db).onboard_company(
            company_name=body.company_name,
            key_name=body.key_name,
            scopes=body.scopes,
            default_model=body.default_model,
        )
        t = result["tenant"]
        k = result["key"]
        return {
            "status": "ok",
            "tenant": _tenant_dict(t),
            "key": _key_dict(k),
            "api_key": result["api_key_plaintext"],
            "warning": "Copy the api_key now. It will never be shown again.",
            "next_steps": result["next_steps"],
            "client_integration": {
                "base_url": "(your Railway public URL)",
                "header": f"X-API-Key: {result['api_key_plaintext'][:20]}…",
                "query": "POST /api/v1/query  {\"question\": \"...\"}",
            },
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ═══════════════════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════════════════


class CreateUserBody(BaseModel):
    email: str
    full_name: str
    role: str = "operator"
    password: str | None = None


class AssignUserBody(BaseModel):
    user_id: str
    tenant_id: str
    role: str = "tenant_member"


@router.get("/admin/users")
def list_users(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = AdminService(db).list_users()
    return {"items": [_user_dict(u) for u in items], "count": len(items)}


@router.post("/admin/users")
def create_user(
    body: CreateUserBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        u = AdminService(db).create_user(
            email=body.email,
            full_name=body.full_name,
            role=body.role,
            password=body.password,
        )
        return {"status": "ok", "user": _user_dict(u)}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.post("/admin/users/assign")
def assign_user(
    body: AssignUserBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        m = AdminService(db).assign_user_to_tenant(
            body.user_id, body.tenant_id, body.role
        )
        return {
            "status": "ok",
            "membership": {
                "id": m.id,
                "user_id": m.user_id,
                "tenant_id": m.tenant_id,
                "role": m.role,
            },
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.get("/admin/tenants/{tenant_id}/members")
def tenant_members(
    tenant_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    svc = AdminService(db)
    members = svc.list_memberships(tenant_id)
    users = {u.id: u for u in svc.list_users()}
    return {
        "items": [
            {
                "id": m.id,
                "user_id": m.user_id,
                "email": users[m.user_id].email if m.user_id in users else None,
                "full_name": users[m.user_id].full_name if m.user_id in users else None,
                "role": m.role,
            }
            for m in members
        ]
    }


# ═══════════════════════════════════════════════════════════════════
# TENANTS
# ═══════════════════════════════════════════════════════════════════


class CreateTenantBody(BaseModel):
    name: str
    slug: str | None = None
    default_model: str | None = None
    rate_limit_rpm: int = 60
    notes: str | None = None


class UpdateTenantBody(BaseModel):
    name: str | None = None
    status: str | None = None
    default_model: str | None = None
    rate_limit_rpm: int | None = None
    notes: str | None = None


@router.get("/admin/tenants")
def list_tenants(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    enriched = AdminService(db).list_tenants_enriched()
    items = []
    for row in enriched:
        d = _tenant_dict(row["tenant"])
        d["keys_active"] = row["keys_active"]
        d["documents"] = row["documents"]
        d["documents_ready"] = row["documents_ready"]
        d["query_count"] = row["query_count"]
        items.append(d)
    return {"items": items, "count": len(items)}


@router.post("/admin/tenants")
def create_tenant(
    body: CreateTenantBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        t = AdminService(db).create_tenant(
            name=body.name,
            slug=body.slug,
            default_model=body.default_model,
            rate_limit_rpm=body.rate_limit_rpm,
            notes=body.notes,
        )
        return {
            "status": "ok",
            "tenant": _tenant_dict(t),
            "next": f"Issue an API key: POST /api/v1/admin/tenants/{t.id}/keys",
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.get("/admin/tenants/{tenant_id}")
def get_tenant(
    tenant_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        detail = AdminService(db).tenant_detail(tenant_id)
        t = detail["tenant"]
        return {
            "tenant": _tenant_dict(t),
            "keys": [_key_dict(k) for k in detail["keys"]],
            "documents": [_doc_dict(d) for d in detail["documents"]],
            "members_count": len(detail["members"]),
            "query_count": detail["query_count"],
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.patch("/admin/tenants/{tenant_id}")
def patch_tenant(
    tenant_id: str,
    body: UpdateTenantBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        t = AdminService(db).update_tenant(
            tenant_id, **body.model_dump(exclude_unset=True)
        )
        return {"status": "ok", "tenant": _tenant_dict(t)}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ═══════════════════════════════════════════════════════════════════
# API KEYS
# ═══════════════════════════════════════════════════════════════════


class CreateKeyBody(BaseModel):
    name: str = "production"
    scopes: list[str] = Field(
        default_factory=lambda: ["query:read", "ingest:write", "docs:read"]
    )


@router.post("/admin/tenants/{tenant_id}/keys")
def create_tenant_key(
    tenant_id: str,
    body: CreateKeyBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        row, raw = AdminService(db).create_key(
            name=body.name,
            tenant_id=tenant_id,
            scopes=body.scopes,
            role="tenant",
        )
        return {
            "status": "ok",
            "key": _key_dict(row),
            "api_key": raw,
            "warning": "Store this key now; it will not be shown again.",
            "client_example": {
                "curl": (
                    f'curl -X POST "$BASE/api/v1/query" '
                    f'-H "X-API-Key: {raw}" '
                    f'-H "Content-Type: application/json" '
                    f'-d \'{{"question":"What is the leave policy?"}}\''
                )
            },
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.post("/admin/keys/platform")
def create_platform_key(
    body: CreateKeyBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        row, raw = AdminService(db).create_key(
            name=body.name or "platform-admin",
            tenant_id=None,
            scopes=["platform:admin"],
            role="platform_admin",
        )
        return {
            "status": "ok",
            "key": _key_dict(row),
            "api_key": raw,
            "warning": "Platform admin key — protect it. Shown once only.",
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.get("/admin/keys")
def list_keys(
    tenant_id: str | None = None,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = AdminService(db).list_keys(tenant_id=tenant_id)
    return {"items": [_key_dict(k) for k in items]}


@router.post("/admin/keys/{key_id}/revoke")
def revoke_key(
    key_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        return {"status": "ok", "key": _key_dict(AdminService(db).revoke_key(key_id))}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.post("/admin/keys/{key_id}/rotate")
def rotate_key(
    key_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        row, raw = AdminService(db).rotate_key(key_id)
        return {
            "status": "ok",
            "key": _key_dict(row),
            "api_key": raw,
            "warning": "New key shown once. Old key revoked.",
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ═══════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════


class ModelBody(BaseModel):
    model_id: str


@router.get("/admin/models")
def list_models(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = AdminService(db).list_models()
    return {
        "items": [
            {
                "model_id": m.model_id,
                "label": m.label,
                "provider": m.provider,
                "enabled": bool(m.enabled),
                "is_default": bool(m.is_default),
            }
            for m in items
        ],
        "embedding": {
            "model": settings.embedding_model,
            "dimension": settings.embedding_dimension,
            "note": "Shared HF embedding model for all tenants (local).",
        },
    }


@router.put("/admin/models/default")
def set_default_model(
    body: ModelBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        m = AdminService(db).set_default_model(body.model_id)
        return {"status": "ok", "model_id": m.model_id, "is_default": True}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.patch("/admin/tenants/{tenant_id}/models")
def tenant_model(
    tenant_id: str,
    body: ModelBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    if not settings.allow_tenant_model_override:
        raise HTTPException(status_code=400, detail="Tenant model override disabled")
    try:
        t = AdminService(db).update_tenant(tenant_id, default_model=body.model_id)
        return {"status": "ok", "tenant": _tenant_dict(t)}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ═══════════════════════════════════════════════════════════════════
# DOCUMENTS (assigned to tenants)
# ═══════════════════════════════════════════════════════════════════


@router.get("/admin/documents")
def list_documents(
    tenant_id: str | None = None,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = DocumentService(db).list_documents(tenant_id=tenant_id)
    return {"items": [_doc_dict(d) for d in items], "count": len(items)}


@router.post("/admin/tenants/{tenant_id}/documents")
async def upload_for_tenant(
    tenant_id: str,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    t = AdminService(db).get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    data = await file.read()
    try:
        doc = DocumentService(db).upload(
            filename=file.filename or "upload.bin",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            namespace=t.pinecone_namespace,
            uploaded_by=principal.key_name,
            process_now=True,
            tenant_id=t.id,
        )
        return {
            "status": "ok",
            "document": _doc_dict(doc),
            "message": f"Document {doc.status}. Vectors in namespace {t.pinecone_namespace}.",
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.post("/admin/documents/{document_id}/reprocess")
def reprocess(
    document_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        doc = DocumentService(db).process_document(document_id)
        return {"status": "ok", "document": _doc_dict(doc)}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.delete("/admin/documents/{document_id}")
def delete_doc(
    document_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        DocumentService(db).delete_document(document_id)
        return {"status": "ok", "deleted": document_id}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ═══════════════════════════════════════════════════════════════════
# USAGE
# ═══════════════════════════════════════════════════════════════════


@router.get("/admin/usage/summary")
def usage_summary(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    from app.services.usage_service import UsageService

    setup = AdminService(db).setup_status()
    return {
        "status": "ok",
        "summary": UsageService(db).summary(),
        "counts": setup["counts"],
    }


@router.get("/admin/usage/events")
def usage_events(
    limit: int = 50,
    tenant_id: str | None = None,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    events = AdminService(db).usage_events(limit=limit, tenant_id=tenant_id)
    return {
        "items": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "tenant_id": e.tenant_id,
                "user_name": e.user_name,
                "latency_ms": e.latency_ms,
                "lag_stage": e.lag_stage,
                "cache_hit": e.cache_hit,
                "model": e.model,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    }


class UserStatusBody(BaseModel):
    status: str


@router.patch("/admin/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserStatusBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        u = AdminService(db).set_user_status(user_id, body.status)
        return {"status": "ok", "user": _user_dict(u)}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@router.delete("/admin/tenants/{tenant_id}/members/{membership_id}")
def remove_member(
    tenant_id: str,
    membership_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    _ = tenant_id
    try:
        AdminService(db).remove_membership(membership_id)
        return {"status": "ok", "removed": membership_id}
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# system health aliases used by UI
@router.get("/admin/system/health")
def system_health(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    s = AdminService(db).setup_status()
    return {"status": "ok", "integrations": s["integrations"], "counts": s["counts"]}


@router.get("/admin/system/config")
def system_config(
    principal: Principal = Depends(require_platform_admin()),
) -> dict:
    _ = principal
    return {
        "product_mode": settings.product_mode,
        "auth_enabled": settings.auth_enabled,
        "enable_admin_ui": settings.enable_admin_ui,
        "enable_chat_ui": settings.enable_chat_ui,
        "default_llm": settings.openrouter_model,
        "embedding_model": settings.embedding_model,
        "api_prefix": settings.api_prefix.rstrip("/") or "/api/v1",
        "public_base_url": (settings.public_base_url or "").rstrip("/"),
        "allow_tenant_model_override": settings.allow_tenant_model_override,
    }
