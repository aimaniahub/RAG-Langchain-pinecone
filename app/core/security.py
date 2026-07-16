"""API key auth helpers (Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, status

from app.config import settings


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated caller."""

    key_name: str
    role: str  # admin | user
    key_id: str  # last 4 only for logs


def _lookup_key(raw_key: str) -> Principal | None:
    raw_key = (raw_key or "").strip()
    if not raw_key:
        return None
    for item in settings.parse_api_keys():
        if item["key"] == raw_key:
            return Principal(
                key_name=item["name"],
                role=item["role"] if item["role"] in {"admin", "user"} else "user",
                key_id=raw_key[-4:] if len(raw_key) >= 4 else "****",
            )
    return None


def extract_api_key(
    x_api_key: str | None = None,
    authorization: str | None = None,
) -> str | None:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return auth
    return None


def authenticate_request(
    x_api_key: str | None = None,
    authorization: str | None = None,
) -> Principal | None:
    """Return principal if auth disabled or key valid; raise 401 if auth on and invalid."""
    if not settings.auth_enabled:
        return Principal(key_name="anonymous", role="admin", key_id="none")

    raw = extract_api_key(x_api_key, authorization)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Send X-API-Key or Authorization: Bearer <key>",
        )
    principal = _lookup_key(raw)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return principal


def require_roles(*roles: str):
    """FastAPI dependency factory: require one of the given roles."""

    async def _dep(
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> Principal:
        principal = authenticate_request(x_api_key, authorization)
        assert principal is not None
        if principal.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{principal.role}' not allowed. Need one of: {', '.join(roles)}",
            )
        request.state.principal = principal
        return principal

    return _dep
