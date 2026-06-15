"""API dependencies and middleware."""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional, Union

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.core.security import verify_token
from app.models.user import User, UserRole
from app.modules.auth import UserService


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Use this when you need a database session outside of FastAPI's
    dependency injection (e.g., in webhook handlers, background tasks).

    Usage:
        async with get_db_session() as db:
            result = await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class OAuth2PasswordBearerOrHTTPBearer(OAuth2PasswordBearer):
    """
    Custom security scheme that supports both OAuth2 password bearer (for Swagger UI)
    and HTTP Bearer token (for manual API usage).
    """
    
    def __init__(self, tokenUrl: str, auto_error: bool = True):
        super().__init__(tokenUrl=tokenUrl, auto_error=auto_error)
        self.http_bearer = HTTPBearer(auto_error=False)
    
    async def __call__(self, request: Request) -> Optional[str]:
        # First try OAuth2 password bearer (for Swagger UI)
        try:
            token = await super().__call__(request)
            if token:
                return token
        except HTTPException:
            pass
        
        # Then try HTTP Bearer (for manual API usage)
        try:
            credentials = await self.http_bearer(request)
            if credentials:
                return credentials.credentials
        except HTTPException:
            pass
        
        # If auto_error is True and no token found, raise exception
        if self.auto_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None


# Security scheme that supports both OAuth2 and Bearer token
security_scheme = OAuth2PasswordBearerOrHTTPBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user_bearer(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user via Bearer token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(credentials.credentials)
    if token_data is None:
        raise credentials_exception

    user_service = UserService(db)
    user = await user_service.get_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_current_user_oauth2(
    token: str = Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user via OAuth2 token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(token)
    if token_data is None:
        raise credentials_exception

    user_service = UserService(db)
    user = await user_service.get_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_current_user(
    token: str = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user (supports both OAuth2 and Bearer token)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(token)
    if token_data is None:
        raise credentials_exception

    user_service = UserService(db)
    user = await user_service.get_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception

    return user


# ──────────────────────────────────────────────────────────────────────────
# Unified current-user (Phase 1b): accept EITHER the existing local HS256 JWT
# OR a central SSO RS256 JWT (with JIT provisioning). Local path is tried
# first for full back-compat; SSO is a fall-through. Nothing here changes the
# behavior of the local-only ``get_current_user`` above.
# ──────────────────────────────────────────────────────────────────────────
async def get_current_user_unified(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current user from a local JWT or an SSO JWT.

    Order:
    1. Local HS256 JWT (existing behavior, unchanged) — back-compat first.
    2. SSO RS256 JWT -> validate via JWKS -> JIT-provision/link a local User.

    The resolved SSO claims (when present) are stashed on ``request.state.sso_claims``
    for downstream enrichment/gating.
    """
    from app.core.sso import get_optional_sso_claims, provision_sso_user, _extract_bearer
    from app.core.security import verify_token as _verify_local

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = _extract_bearer(request)
    if not token:
        raise credentials_exception

    # 1) Local JWT first (back-compat). verify_token returns None on RS256/SSO.
    token_data = _verify_local(token)
    if token_data is not None:
        user_service = UserService(db)
        user = await user_service.get_by_id(token_data.user_id)
        if user is not None:
            return user
        raise credentials_exception

    # 2) SSO fall-through (RS256). JIT-provision on first sight.
    claims = await get_optional_sso_claims(request)
    if claims is not None:
        request.state.sso_claims = claims
        return await provision_sso_user(db, claims)

    raise credentials_exception


async def get_current_active_user_unified(
    current_user: User = Depends(get_current_user_unified),
) -> User:
    """Active-user variant of the unified (local-or-SSO) dependency."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


async def get_current_verified_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Get current verified user."""
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not verified"
        )
    return current_user


def require_role(required_role: UserRole):
    """Require specific user role."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        # Platform owner has access to everything
        if current_user.role == UserRole.PLATFORM_OWNER:
            return current_user
        # ISP_ADMIN is treated as the legacy ADMIN for backwards compatibility
        if current_user.role == UserRole.ISP_ADMIN and required_role == UserRole.ADMIN:
            return current_user
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


def require_admin():
    """Require admin role (ISP_ADMIN or PLATFORM_OWNER)."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        # Support both old ADMIN role and new ISP_ADMIN role
        admin_roles = [UserRole.PLATFORM_OWNER, UserRole.ISP_ADMIN]
        # Also support legacy ADMIN if it exists in enum
        if hasattr(UserRole, 'ADMIN'):
            admin_roles.append(UserRole.ADMIN)
        if current_user.role not in admin_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


def require_technician_or_admin():
    """Require technician or admin role."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        # Support both old and new role names
        allowed_roles = [UserRole.PLATFORM_OWNER, UserRole.ISP_ADMIN, UserRole.ISP_TECHNICIAN]
        # Also support legacy roles if they exist
        if hasattr(UserRole, 'ADMIN'):
            allowed_roles.append(UserRole.ADMIN)
        if hasattr(UserRole, 'TECHNICIAN'):
            allowed_roles.append(UserRole.TECHNICIAN)
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


def require_customer_or_admin():
    """Require customer or admin role."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        allowed_roles = [UserRole.PLATFORM_OWNER, UserRole.ISP_ADMIN, UserRole.CUSTOMER]
        # Also support legacy ADMIN if it exists
        if hasattr(UserRole, 'ADMIN'):
            allowed_roles.append(UserRole.ADMIN)
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


# ──────────────────────────────────────────────────────────────────────────
# Multi-outlet scope (Phase 5) — OPTIONAL, ADDITIVE.
#
# Clients (e.g. a per-outlet POS/admin UI) may send an ``X-Outlet-ID`` header to
# scope reads/writes to a single outlet. This dependency parses it and returns
# it as ``Optional[int]`` — it NEVER requires the header and NEVER errors when
# it is absent or malformed (returns None), so every existing caller that omits
# it is completely unaffected. Routers thread it into queries only as an
# additional ``WHERE`` filter when present.
# ──────────────────────────────────────────────────────────────────────────
def get_outlet_id(request: Request) -> Optional[int]:
    """Return the X-Outlet-ID header as an int, or None when absent/invalid."""
    raw = request.headers.get("X-Outlet-ID") or request.headers.get("x-outlet-id")
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


class PaginationParams:
    """Pagination parameters."""

    def __init__(
        self,
        page: int = 1,
        size: int = 20,
        max_size: int = 100,
    ):
        if page < 1:
            page = 1
        if size < 1:
            size = 20
        if size > max_size:
            size = max_size
        
        self.page = page
        self.size = size
        self.offset = (page - 1) * size


def get_pagination_params(
    page: int = 1,
    size: int = 20,
) -> PaginationParams:
    """Get pagination parameters."""
    return PaginationParams(page=page, size=size)


# ──────────────────────────────────────────────────────────────────────────
# Subscription gating (Phase 1b) — OPT-IN dependency.
#
# For MUTATING requests (POST/PUT/PATCH/DELETE) made by an SSO user who is NOT
# a platform owner / superuser, returns 403 {code: "subscription_inactive",
# upgrade: true} when the SSO subscription status is not ACTIVE. Reads (GET,
# HEAD, OPTIONS) are always allowed. Local-JWT users and S2S callers are NOT
# gated (no SSO subscription claims), preserving existing behavior.
#
# This is a DEPENDENCY (not global middleware) precisely so it is never
# accidentally applied to the public captive-portal / hotspot / pppoe routes.
# Wire it into ISP-admin business routers only, e.g.:
#     router = APIRouter(dependencies=[Depends(enforce_subscription_active)])
# ──────────────────────────────────────────────────────────────────────────
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def enforce_subscription_active(request: Request) -> None:
    """Gate mutating SSO requests on an ACTIVE subscription. Opt-in."""
    if request.method.upper() in _SAFE_METHODS:
        return

    from app.core.sso import get_optional_sso_claims, is_internal_service_request

    # Trusted S2S callers bypass subscription gating.
    if is_internal_service_request(request):
        return

    # Only SSO-authenticated requests carry subscription claims. Local-JWT
    # users have none and are intentionally not gated here (back-compat).
    claims = getattr(request.state, "sso_claims", None)
    if claims is None:
        claims = await get_optional_sso_claims(request)
    if claims is None:
        return

    # Platform owners / superusers are never gated.
    if claims.get("is_platform_owner"):
        return
    roles = {str(r).strip().lower() for r in (claims.get("roles") or [])}
    if roles & {"platform_owner", "superuser"}:
        return

    sub_status = str(claims.get("sub_status", "")).strip().upper()
    if sub_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "subscription_inactive",
                "upgrade": True,
                "message": "An active subscription is required for this action.",
            },
        )


# ──────────────────────────────────────────────────────────────────────────
# Plan-LIMIT gating (Phase 3) — central subscriptions-api migration.
#
# enforce_plan_limit(limit_key, count_fn) returns a FastAPI dependency that
# blocks a CREATE/mutation when the tenant has reached the per-plan limit
# (e.g. max_routers, max_customers) defined in the central subscriptions-api.
#
# Limit resolution (fast → slow):
#   1. SSO JWT claims `sub_limits` (enriched by auth-api from subscriptions-api)
#   2. fallback: live read via SubscriptionsClient.get_subscription(tenant_uuid)
#
# DEGRADES SAFELY (migration-safe): if NO subscription limit information is
# available — local-JWT user, no SSO claims, subscriptions-api not configured /
# unreachable, tenant not yet subscribed, or the limit key absent — the action
# is ALLOWED (current behavior preserved) and a warning is logged. A limit value
# of -1 (or 0) means unlimited. Superuser / platform owner always bypass.
# ──────────────────────────────────────────────────────────────────────────
def _limit_is_unlimited(value: Any) -> bool:
    """A plan limit of -1 (convention) or non-positive means "no cap"."""
    try:
        return int(value) <= 0
    except (TypeError, ValueError):
        return True


def _claims_bypass_limits(claims: dict) -> bool:
    """Platform owners / superusers are never limit-gated."""
    if claims.get("is_platform_owner"):
        return True
    roles = {str(r).strip().lower() for r in (claims.get("roles") or [])}
    return bool(roles & {"platform_owner", "superuser"})


def enforce_plan_limit(limit_key: str, count_fn):
    """Build a dependency enforcing a per-plan numeric limit on a CREATE.

    Args:
        limit_key: the limit name in `sub_limits` / subscription `limits`
            (e.g. "max_routers", "max_customers").
        count_fn: ``async (db, organization_id) -> int`` returning the tenant's
            current usage count for that resource. ``organization_id`` may be
            ``None`` (platform-wide); count_fn should handle that.

    The returned dependency raises 403 {code: "usage_limit_exceeded",
    upgrade: true} when current usage >= the resolved limit; otherwise allows.
    """

    async def _dep(
        request: Request,
        current_user: "User" = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        import logging as _logging

        log = _logging.getLogger(__name__)

        from app.core.sso import get_optional_sso_claims, is_internal_service_request

        # Trusted S2S callers are never limit-gated.
        if is_internal_service_request(request):
            return

        # Local-platform-owner role also bypasses (mirrors org-id "see all").
        if getattr(current_user, "role", None) == UserRole.PLATFORM_OWNER:
            return

        claims = getattr(request.state, "sso_claims", None)
        if claims is None:
            claims = await get_optional_sso_claims(request)

        # No SSO claims → local-JWT request: no central subscription context.
        # Migration-safe: ALLOW (local Licence model still governs limits).
        if not claims:
            log.warning(
                "enforce_plan_limit(%s): no SSO claims on request — allowing "
                "(local Licence model still authoritative during migration)",
                limit_key,
            )
            return

        if _claims_bypass_limits(claims):
            return

        # 1) Fast path: limit from JWT sub_limits claim.
        limit_value: Any = None
        sub_limits = claims.get("sub_limits") or {}
        if isinstance(sub_limits, dict) and limit_key in sub_limits:
            limit_value = sub_limits.get(limit_key)

        tenant_id = claims.get("tenant_id")

        # 2) Slow path: live read from subscriptions-api when the claim is absent.
        if limit_value is None and tenant_id:
            try:
                from app.services.subscriptions_client import get_subscriptions_client

                sub = await get_subscriptions_client().get_subscription(str(tenant_id))
                if sub:
                    limits = sub.get("limits") or {}
                    if isinstance(limits, dict):
                        limit_value = limits.get(limit_key)
            except Exception as exc:  # never block on a subscriptions outage
                log.warning(
                    "enforce_plan_limit(%s): subscriptions-api lookup failed "
                    "(%s) — allowing (fail-open during migration)",
                    limit_key,
                    exc,
                )
                return

        # No limit info anywhere → migration-safe ALLOW.
        if limit_value is None:
            log.warning(
                "enforce_plan_limit(%s): no limit found in claims or "
                "subscriptions-api — allowing (fail-open during migration)",
                limit_key,
            )
            return

        if _limit_is_unlimited(limit_value):
            return

        try:
            limit_int = int(limit_value)
        except (TypeError, ValueError):
            return  # unparseable limit → allow rather than block

        org_id = (
            None
            if getattr(current_user, "role", None) == UserRole.PLATFORM_OWNER
            else getattr(current_user, "organization_id", None)
        )
        try:
            current = int(await count_fn(db, org_id))
        except Exception as exc:  # counting failed → don't block the user
            log.warning(
                "enforce_plan_limit(%s): usage count failed (%s) — allowing",
                limit_key,
                exc,
            )
            return

        if current >= limit_int:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "usage_limit_exceeded",
                    "upgrade": True,
                    "limit": limit_int,
                    "current": current,
                    "limit_key": limit_key,
                    "message": (
                        f"Your plan allows up to {limit_int} for {limit_key}. "
                        "Upgrade your plan to add more."
                    ),
                },
            )

    return _dep
