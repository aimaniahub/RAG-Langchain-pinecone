"""Platform admin API — tenants, keys, models (control plane)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.core.security import Principal, require_platform_admin
from app.db.session import check_db, get_db
from app.services.platform_service import PlatformService
from app.services.usage_service import UsageService
from app.storage.s3_client import get_storage
from fastapi import HTTPException

router = APIRouter(tags=["platform-admin"])


def _map(exc: Exception) -> HTTPException:
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.message)
    return HTTPException(status_code=500, detail="Internal server error")


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


# ---------- System ----------
@router.get("/admin/system/health")
def system_health(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    storage_ok = False
    try:
        storage_ok = get_storage().health_check()
    except Exception:  # noqa: BLE001
        storage_ok = False
    return {
        "status": "ok",
        "integrations": {
            "database": check_db(),
            "storage": storage_ok,
            "storage_backend": settings.storage_backend,
            "openrouter": settings.is_openrouter_configured,
            "pinecone": settings.is_pinecone_configured,
        },
        "product_mode": settings.product_mode,
        "embedding_model": settings.embedding_model,
        "default_llm": settings.openrouter_model,
    }


@router.get("/admin/system/config")
def system_config(
    principal: Principal = Depends(require_platform_admin()),
) -> dict:
    _ = principal
    return {
        "product_mode": settings.product_mode,
        "auth_enabled": settings.auth_enabled,
        "enable_chat_ui": settings.enable_chat_ui,
        "enable_dev_ui": settings.enable_dev_ui,
        "enable_admin_ui": settings.enable_admin_ui,
        "allow_tenant_model_override": settings.allow_tenant_model_override,
        "default_openrouter_model": settings.openrouter_model,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "api_prefix": settings.api_prefix,
    }


# ---------- Tenants ----------
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


@router.post("/admin/tenants")
def create_tenant(
    body: CreateTenantBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        t = PlatformService(db).create_tenant(
            name=body.name,
            slug=body.slug,
            default_model=body.default_model,
            rate_limit_rpm=body.rate_limit_rpm,
            notes=body.notes,
        )
        return {"status": "ok", "tenant": _tenant_dict(t)}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.get("/admin/tenants")
def list_tenants(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = PlatformService(db).list_tenants()
    return {"items": [_tenant_dict(t) for t in items], "count": len(items)}


@router.get("/admin/tenants/{tenant_id}")
def get_tenant(
    tenant_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    t = PlatformService(db).get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"tenant": _tenant_dict(t)}


@router.patch("/admin/tenants/{tenant_id}")
def patch_tenant(
    tenant_id: str,
    body: UpdateTenantBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        t = PlatformService(db).update_tenant(
            tenant_id,
            **body.model_dump(exclude_unset=True),
        )
        return {"status": "ok", "tenant": _tenant_dict(t)}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


# ---------- Keys ----------
class CreateKeyBody(BaseModel):
    name: str = "default"
    scopes: list[str] = Field(default_factory=lambda: ["query:read", "ingest:write"])
    role: str = "tenant"  # tenant | platform_admin


@router.post("/admin/tenants/{tenant_id}/keys")
def create_tenant_key(
    tenant_id: str,
    body: CreateKeyBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        row, raw = PlatformService(db).create_key(
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
        }
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.post("/admin/keys/platform")
def create_platform_key(
    body: CreateKeyBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        row, raw = PlatformService(db).create_key(
            name=body.name,
            tenant_id=None,
            scopes=body.scopes,
            role="platform_admin",
        )
        return {
            "status": "ok",
            "key": _key_dict(row),
            "api_key": raw,
            "warning": "Store this key now; it will not be shown again.",
        }
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.get("/admin/tenants/{tenant_id}/keys")
def list_tenant_keys(
    tenant_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = PlatformService(db).list_keys(tenant_id=tenant_id)
    return {"items": [_key_dict(k) for k in items]}


@router.get("/admin/keys")
def list_all_keys(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = PlatformService(db).list_keys()
    return {"items": [_key_dict(k) for k in items]}


@router.post("/admin/keys/{key_id}/revoke")
def revoke_key(
    key_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        row = PlatformService(db).revoke_key(key_id)
        return {"status": "ok", "key": _key_dict(row)}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.post("/admin/keys/{key_id}/rotate")
def rotate_key(
    key_id: str,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        row, raw = PlatformService(db).rotate_key(key_id)
        return {
            "status": "ok",
            "key": _key_dict(row),
            "api_key": raw,
            "warning": "Store this key now; it will not be shown again.",
        }
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


# ---------- Models ----------
class DefaultModelBody(BaseModel):
    model_id: str


class EnableModelBody(BaseModel):
    enabled: bool = True


@router.get("/admin/models")
def list_models(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    items = PlatformService(db).list_models()
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
        },
    }


@router.put("/admin/models/default")
def set_default_model(
    body: DefaultModelBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        m = PlatformService(db).set_default_model(body.model_id)
        return {
            "status": "ok",
            "model_id": m.model_id,
            "note": "Catalog default updated. Tenant overrides still apply. "
            "Set OPENROUTER_MODEL env for process default on restart.",
        }
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.patch("/admin/models/{model_id}")
def enable_model(
    model_id: str,
    body: EnableModelBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        m = PlatformService(db).set_model_enabled(model_id, body.enabled)
        return {
            "status": "ok",
            "model_id": m.model_id,
            "enabled": bool(m.enabled),
        }
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.patch("/admin/tenants/{tenant_id}/models")
def tenant_model(
    tenant_id: str,
    body: DefaultModelBody,
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    if not settings.allow_tenant_model_override:
        raise HTTPException(status_code=400, detail="Tenant model override disabled")
    try:
        t = PlatformService(db).update_tenant(tenant_id, default_model=body.model_id)
        return {"status": "ok", "tenant": _tenant_dict(t)}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


# ---------- Usage ----------
@router.get("/admin/usage/summary")
def usage_summary(
    principal: Principal = Depends(require_platform_admin()),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    summary = UsageService(db).summary()
    by_tenant = PlatformService(db).usage_by_tenant()
    return {"status": "ok", "summary": summary, "by_tenant": by_tenant}
