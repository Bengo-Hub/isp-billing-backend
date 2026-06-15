"""SSO (auth-api / Codevertex SSO) token validation + JIT provisioning.

Phase 1b: ADDITIVE SSO acceptance alongside the existing local JWT login.

This module is self-contained and does NOT touch the local-JWT path:
- ``SSOValidator`` validates an RS256 JWT minted by the central SSO issuer
  (https://sso.codevertexitsolutions.com) using JWKS (keys cached via
  PyJWKClient), checking signature, exp, iss and aud.
- ``get_sso_claims`` is a FastAPI dependency returning the parsed claims (or
  raising 401). It is OPTIONAL-friendly via ``get_optional_sso_claims``.
- ``verify_service_key`` trusts internal S2S callers presenting
  ``X-API-Key == INTERNAL_SERVICE_KEY``.
- ``provision_sso_user`` performs JIT create/link of a local ``User`` from SSO
  claims, mapping global roles to the existing ISP ``UserRole`` enum and
  reusing the existing role/permission tables.

NOTE: hotspot/PPPoE end-user (captive portal) auth is intentionally untouched;
nothing here is wired into app/api/v1/portal/*.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

import jwt
from jwt import PyJWKClient
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole, UserStatus

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# JWKS validator (keys cached by PyJWKClient)
# ──────────────────────────────────────────────────────────────────────────
class SSOValidator:
    """Validates RS256 SSO JWTs using the issuer's JWKS endpoint."""

    def __init__(self) -> None:
        self._jwks_client: Optional[PyJWKClient] = None

    @property
    def jwks_url(self) -> str:
        # Prefer an explicit JWKS URL; otherwise derive the conventional path.
        if getattr(settings, "sso_jwks_url", None):
            return settings.sso_jwks_url
        return settings.sso_issuer.rstrip("/") + "/.well-known/jwks.json"

    def _client(self) -> PyJWKClient:
        if self._jwks_client is None:
            # PyJWKClient caches fetched signing keys in-process.
            self._jwks_client = PyJWKClient(self.jwks_url, cache_keys=True)
        return self._jwks_client

    def decode(self, token: str) -> Dict[str, Any]:
        """Validate signature/exp/iss/aud and return the claim set.

        Raises ``jwt.PyJWTError`` subclasses on any validation failure.
        """
        signing_key = self._client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.sso_audience,
            issuer=settings.sso_issuer,
            options={"require": ["exp", "iss"]},
        )
        return claims


# Module-level singleton so the JWKS cache persists across requests.
_validator = SSOValidator()


def get_validator() -> SSOValidator:
    return _validator


_bearer = HTTPBearer(auto_error=False)


def _extract_bearer(request: Request) -> Optional[str]:
    """Pull a raw bearer token from the Authorization header, if present."""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def looks_like_sso_token(token: str) -> bool:
    """Heuristic: is this an SSO (RS256) token vs a local HS256 token?

    Cheap, signature-free header peek so the unified dependency can try the
    local path first and only fall through to SSO for RS256 tokens.
    """
    try:
        header = jwt.get_unverified_header(token)
        return str(header.get("alg", "")).upper().startswith("RS")
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────
# FastAPI dependencies
# ──────────────────────────────────────────────────────────────────────────
async def get_sso_claims(request: Request) -> Dict[str, Any]:
    """Require a valid SSO JWT; return its claims. Raises 401 otherwise."""
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return get_validator().decode(token)
    except jwt.PyJWTError as exc:
        logger.info("SSO token validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid SSO token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_sso_claims(request: Request) -> Optional[Dict[str, Any]]:
    """Return SSO claims if a valid SSO token is present, else None.

    Never raises — used by the unified current-user dependency to try SSO
    after the local-JWT path declines.
    """
    token = _extract_bearer(request)
    if not token or not looks_like_sso_token(token):
        return None
    try:
        return get_validator().decode(token)
    except jwt.PyJWTError as exc:
        logger.info("Optional SSO token validation failed: %s", exc)
        return None


async def verify_service_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> bool:
    """S2S guard: trust callers presenting the shared INTERNAL_SERVICE_KEY."""
    expected = (settings.internal_service_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal service key not configured",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service key",
        )
    return True


def is_internal_service_request(request: Request) -> bool:
    """Best-effort check for a trusted S2S caller (no raise)."""
    expected = (settings.internal_service_key or "").strip()
    if not expected:
        return False
    provided = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    return bool(provided) and secrets.compare_digest(provided, expected)


# ──────────────────────────────────────────────────────────────────────────
# Role mapping + JIT provisioning
# ──────────────────────────────────────────────────────────────────────────
def map_global_roles_to_isp_role(
    roles: List[str], is_platform_owner: bool = False
) -> UserRole:
    """Map SSO global roles[] to the existing ISP UserRole enum.

    superuser/admin -> ISP_ADMIN (PLATFORM_OWNER when is_platform_owner)
    technician       -> ISP_TECHNICIAN
    customer         -> CUSTOMER
    anything else    -> CUSTOMER (viewer-equivalent / least privilege)
    """
    normalized = {str(r).strip().lower() for r in (roles or [])}

    if is_platform_owner or "platform_owner" in normalized:
        return UserRole.PLATFORM_OWNER
    if normalized & {"superuser", "admin", "isp_admin", "owner"}:
        return UserRole.ISP_ADMIN
    if normalized & {"technician", "isp_technician", "staff", "support"}:
        return UserRole.ISP_TECHNICIAN
    if normalized & {"customer", "subscriber", "end_user"}:
        return UserRole.CUSTOMER
    # Least-privilege fallback (viewer-equivalent).
    return UserRole.CUSTOMER


def _isp_role_to_rbac_role_name(role: UserRole) -> str:
    """Map the ISP ``UserRole`` enum to the seeded RBAC ``Role.name``.

    The RBAC ``Role`` row (seeded in ``_seed_rbac``) is what actually carries the
    permission set; these names must match the roles created there
    (superuser / admin / technician / customer).
    """
    return {
        UserRole.PLATFORM_OWNER: "superuser",
        UserRole.ISP_ADMIN: "admin",
        UserRole.ISP_TECHNICIAN: "technician",
        UserRole.CUSTOMER: "customer",
    }.get(role, "customer")


async def _sync_role_obj(db: AsyncSession, user: User) -> None:
    """Link ``user.role_obj`` to the RBAC ``Role`` matching ``user.role``.

    SSO/JIT provisioning sets the ``UserRole`` enum column but historically never
    linked the ``Role`` FK. Because the permission set lives on the ``Role``
    (``role_obj.permissions``), an unlinked ``role_obj`` makes ``/auth/me`` return
    an empty ``permissions`` list for every SSO user. This (idempotently) resolves
    the matching Role — with its permissions eagerly loaded — and assigns it.
    Only writes when the link is missing or stale.
    """
    from app.models.rbac import Role
    from sqlalchemy.orm import selectinload

    desired = _isp_role_to_rbac_role_name(user.role)
    # Always (re)assign rather than reading the current role_obj first: reading the
    # relationship on a freshly-refreshed user could trigger an async lazy-load,
    # whereas *setting* it never does, and re-assigning the same Role is harmless.
    res = await db.execute(
        select(Role).where(Role.name == desired).options(selectinload(Role.permissions))
    )
    role = res.scalar_one_or_none()
    if role is not None:
        user.role_obj = role


async def _resolve_organization_id(
    db: AsyncSession, claims: Dict[str, Any]
) -> Optional[int]:
    """Best-effort tenant resolution from SSO claims (slug, then uuid).

    Returns None for platform owners or when the tenant cannot be matched
    locally — JIT still links the user; org can be backfilled later.
    """
    from app.models.organization import Organization

    slug = claims.get("tenant_slug")
    if slug:
        res = await db.execute(select(Organization).where(Organization.slug == slug))
        org = res.scalar_one_or_none()
        if org:
            return org.id

    tenant_id = claims.get("tenant_id")
    if tenant_id:
        try:
            res = await db.execute(
                select(Organization).where(Organization.uuid == tenant_id)
            )
            org = res.scalar_one_or_none()
            if org:
                return org.id
        except Exception:  # invalid uuid string etc. — non-fatal
            pass
    return None


def _split_name(full_name: Optional[str], email: str) -> tuple[str, str]:
    if full_name and full_name.strip():
        parts = full_name.strip().split(" ", 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""
        return first, (last or first)
    local = (email or "user").split("@", 1)[0]
    return local, local


async def provision_sso_user(db: AsyncSession, claims: Dict[str, Any]) -> User:
    """JIT create/link a local User from SSO claims.

    Match order: auth_service_user_id (sub) -> email. On first sight, create a
    new local User. On subsequent sights, link/refresh the mapping. Role is
    (re)mapped from global roles on every sync so RBAC stays in step with SSO.
    """
    from app.models.rbac import Role, UserPermission
    from sqlalchemy.orm import selectinload

    sub = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    if not sub and not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SSO token missing subject/email",
        )

    roles = claims.get("roles") or []
    is_platform_owner = bool(claims.get("is_platform_owner"))
    isp_role = map_global_roles_to_isp_role(roles, is_platform_owner)

    eager = (
        selectinload(User.role_obj).selectinload(Role.permissions),
        selectinload(User.permission_overrides).selectinload(UserPermission.permission),
    )

    # 1) Try by auth_service_user_id (the SSO subject).
    user: Optional[User] = None
    if sub:
        res = await db.execute(
            select(User).where(User.auth_service_user_id == str(sub)).options(*eager)
        )
        user = res.scalar_one_or_none()

    # 2) Fall back to email (links a pre-existing local account to SSO).
    if user is None and email:
        res = await db.execute(
            select(User).where(User.email == email).options(*eager)
        )
        user = res.scalar_one_or_none()

    org_id = await _resolve_organization_id(db, claims)

    if user is not None:
        # Link + refresh mapping (idempotent).
        if sub and user.auth_service_user_id != str(sub):
            user.auth_service_user_id = str(sub)
        user.auth_synced_at = datetime.utcnow()
        # Role sync WITHOUT clobbering: auth.user.* events don't carry tenant-
        # membership roles (those live in auth's tenant_memberships + the login
        # JWT), so an event-time sync would otherwise downgrade a real ISP_ADMIN
        # back to CUSTOMER on every redelivery. Policy: only change the role when
        # the incoming claims actually carry role info (a JWT login, or an event
        # with roles); when roles are absent, keep the existing local role.
        _rank = {
            UserRole.CUSTOMER: 0,
            UserRole.ISP_TECHNICIAN: 1,
            UserRole.ISP_ADMIN: 2,
            UserRole.PLATFORM_OWNER: 3,
        }
        incoming_has_roles = bool(roles) or is_platform_owner
        if incoming_has_roles and user.role != isp_role:
            # Apply upgrades always; apply an explicit demotion only when the
            # incoming role is non-trivial (not the empty->CUSTOMER default).
            if _rank.get(isp_role, 0) >= _rank.get(user.role, 0) or isp_role != UserRole.CUSTOMER:
                user.role = isp_role
        if org_id is not None and user.organization_id is None and not is_platform_owner:
            user.organization_id = org_id
        # Link the RBAC Role (carries the permission set) to the (possibly just
        # updated) enum role. Heals already-provisioned SSO users whose role_obj
        # was never linked — the cause of empty /auth/me permissions.
        await _sync_role_obj(db, user)
        await db.commit()
        # Re-fetch with RBAC relationships eagerly loaded so downstream readers
        # (e.g. /auth/me) can access role_obj.permissions without a lazy load.
        res = await db.execute(select(User).where(User.id == user.id).options(*eager))
        return res.scalar_one()

    # 3) Create a fresh local user (JIT).
    first, last = _split_name(claims.get("full_name"), email)
    # Username must be unique; derive from email local-part, de-dupe if needed.
    base_username = (email.split("@", 1)[0] if email else f"sso_{sub}")[:40] or f"sso_{sub}"
    username = base_username
    suffix = 1
    while True:
        exists = await db.execute(select(User).where(User.username == username))
        if exists.scalar_one_or_none() is None:
            break
        username = f"{base_username}_{suffix}"[:50]
        suffix += 1

    user = User(
        organization_id=None if is_platform_owner else org_id,
        username=username,
        email=email or f"{username}@sso.local",
        first_name=first,
        last_name=last,
        # SSO users authenticate via the IdP; set an unusable random local hash
        # so the local password path can never authenticate them.
        hashed_password="!sso!" + secrets.token_urlsafe(24),
        role=isp_role,
        status=UserStatus.ACTIVE,
        is_active=True,
        is_verified=True,
        auth_service_user_id=str(sub) if sub else None,
        auth_synced_at=datetime.utcnow(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # Link the RBAC Role so role_obj.permissions resolves for /auth/me.
    await _sync_role_obj(db, user)
    await db.commit()
    logger.info(
        "JIT-provisioned SSO user id=%s email=%s role=%s org=%s",
        user.id, user.email, isp_role.value, user.organization_id,
    )

    # Re-fetch with RBAC relationships eagerly loaded for downstream use.
    res = await db.execute(select(User).where(User.id == user.id).options(*eager))
    return res.scalar_one()
