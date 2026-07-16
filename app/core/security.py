"""API key auth — env bootstrap + DB tenant keys + scopes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db


@dataclass(slots=True)
class Principal:
    """Authenticated caller with tenant context."""

    key_name: str
    role: str  # platform_admin | tenant | admin | user (legacy)
    key_id: str  # short id for logs
    tenant_id: str | None = None
    tenant_slug: str | None = None
    namespace: str = "default"
    scopes: frozenset[str] = field(default_factory=frozenset)
    openrouter_model: str | None = None
    api_key_db_id: str | None = None
    rate_limit_rpm: int | None = None

    def has_scope(self, scope: str) -> bool:
        if self.role in {"platform_admin", "admin"}:
            return True
        if "platform:admin" in self.scopes:
            return True
        return scope in self.scopes

    @property
    def is_platform_admin(self) -> bool:
        return self.role in {"platform_admin", "admin"} or "platform:admin" in self.scopes


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def key_prefix(raw_key: str) -> str:
    raw = raw_key.strip()
    return raw[:16] if len(raw) >= 16 else raw


def extract_api_key(
    x_api_key: str | None = None,
    authorization: str | None = None,
) -> str | None:
    from app.config import Settings

    if x_api_key:
        cleaned = Settings.clean_secret(x_api_key)
        if cleaned:
            return cleaned
    if authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            cleaned = Settings.clean_secret(auth[7:])
            if cleaned:
                return cleaned
        cleaned = Settings.clean_secret(auth)
        if cleaned:
            return cleaned
    return None


def _env_principal(raw_key: str) -> Principal | None:
    """Match raw key against API_KEY_ADMIN / BOOTSTRAP_ADMIN_KEY / API_KEYS_JSON."""
    from app.config import Settings

    cleaned = Settings.clean_secret(raw_key)
    if not cleaned:
        return None
    for item in settings.parse_api_keys():
        if item["key"] != cleaned:
            continue
        role = (item.get("role") or "user").lower()
        if role in {"admin", "platform_admin"}:
            return Principal(
                key_name=item["name"],
                role="platform_admin",
                key_id=cleaned[-4:] if len(cleaned) >= 4 else "****",
                tenant_id=None,
                namespace=settings.pinecone_namespace or "default",
                scopes=frozenset(
                    {
                        "platform:admin",
                        "query:read",
                        "ingest:write",
                        "docs:read",
                    }
                ),
                openrouter_model=settings.openrouter_model,
            )
        return Principal(
            key_name=item["name"],
            role="tenant",
            key_id=cleaned[-4:] if len(cleaned) >= 4 else "****",
            tenant_id=None,
            namespace=settings.pinecone_namespace or "default",
            scopes=frozenset({"query:read", "docs:read"}),
            openrouter_model=settings.openrouter_model,
        )
    return None


def _db_principal(db: Session, raw_key: str) -> Principal | None:
    from app.db.models import ApiKey, Tenant

    h = hash_api_key(raw_key)
    row = db.query(ApiKey).filter(ApiKey.key_hash == h, ApiKey.status == "active").first()
    if not row:
        return None

    tenant: Tenant | None = None
    namespace = settings.pinecone_namespace or "default"
    model = settings.openrouter_model
    tenant_slug = None
    rate = None

    if row.tenant_id:
        tenant = db.get(Tenant, row.tenant_id)
        if not tenant or tenant.status != "active":
            return None
        namespace = tenant.pinecone_namespace
        tenant_slug = tenant.slug
        model = tenant.default_model or settings.openrouter_model
        rate = tenant.rate_limit_rpm

    scopes = frozenset(s.strip() for s in (row.scopes or "").split(",") if s.strip())
    role = row.role if row.role in {"platform_admin", "tenant"} else "tenant"
    if role == "platform_admin":
        scopes = scopes | frozenset(
            {"platform:admin", "query:read", "ingest:write", "docs:read"}
        )

    row.last_used_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()

    return Principal(
        key_name=row.name,
        role=role,
        key_id=row.key_prefix[-4:] if row.key_prefix else "****",
        tenant_id=row.tenant_id,
        tenant_slug=tenant_slug,
        namespace=namespace,
        scopes=scopes,
        openrouter_model=model,
        api_key_db_id=row.id,
        rate_limit_rpm=rate,
    )


def authenticate_request(
    db: Session | None = None,
    x_api_key: str | None = None,
    authorization: str | None = None,
) -> Principal:
    """Resolve principal from DB keys first, then env bootstrap keys."""
    if not settings.auth_enabled:
        return Principal(
            key_name="anonymous",
            role="platform_admin",
            key_id="none",
            namespace=settings.pinecone_namespace or "default",
            scopes=frozenset(
                {"platform:admin", "query:read", "ingest:write", "docs:read"}
            ),
            openrouter_model=settings.openrouter_model,
        )

    raw = extract_api_key(x_api_key, authorization)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Send X-API-Key or Authorization: Bearer <key>",
        )

    # Env bootstrap first so a newly set API_KEY_ADMIN always works even if an
    # old/disabled DB hash collides or DB is briefly unavailable.
    principal = _env_principal(raw)
    if principal is None and db is not None:
        try:
            principal = _db_principal(db, raw)
        except Exception:  # noqa: BLE001
            principal = None
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid API key. Use the platform admin key from env "
                "(API_KEY_ADMIN or BOOTSTRAP_ADMIN_KEY) or a DB-issued platform key."
            ),
        )
    if not principal.is_platform_admin and "platform:admin" not in principal.scopes:
        # Tenant keys must not call admin routes; require_scopes enforces this.
        pass
    return principal


def require_auth():
    """Any valid API key."""

    async def _dep(
        request: Request,
        db: Session = Depends(get_db),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> Principal:
        principal = authenticate_request(db, x_api_key, authorization)
        request.state.principal = principal
        return principal

    return _dep


def require_scopes(*scopes: str):
    """Require all listed scopes (platform admin bypasses)."""

    async def _dep(
        request: Request,
        db: Session = Depends(get_db),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> Principal:
        principal = authenticate_request(db, x_api_key, authorization)
        missing = [s for s in scopes if not principal.has_scope(s)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing scopes: {', '.join(missing)}",
            )
        request.state.principal = principal
        return principal

    return _dep


def require_platform_admin():
    return require_scopes("platform:admin")


def require_roles(*roles: str):
    """Legacy role check; maps admin/user to platform_admin/tenant."""

    async def _dep(
        request: Request,
        db: Session = Depends(get_db),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> Principal:
        principal = authenticate_request(db, x_api_key, authorization)
        mapped = set(roles)
        if "admin" in mapped:
            mapped.add("platform_admin")
        if "user" in mapped:
            mapped.add("tenant")
        if principal.role not in mapped and not principal.is_platform_admin:
            # allow platform admin always for admin routes
            if "admin" in roles or "platform_admin" in roles:
                if not principal.is_platform_admin:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Platform admin required",
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role '{principal.role}' not allowed",
                )
        if ("admin" in roles or "platform_admin" in roles) and not principal.is_platform_admin:
            if principal.role not in mapped:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Platform admin required",
                )
        request.state.principal = principal
        return principal

    return _dep
