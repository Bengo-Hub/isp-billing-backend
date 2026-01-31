"""
Tenant middleware for multi-tenancy support.

Resolves the current tenant (organization) from various sources:
1. JWT token (organization_id claim)
2. Subdomain (org-slug.ispbilling.com)
3. Custom domain (portal.ispname.com)
4. API Header (X-Tenant-ID)
"""

import contextvars
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

if TYPE_CHECKING:
    from app.models.organization import Organization

# Context variable to store current tenant
_current_tenant: contextvars.ContextVar[Optional["Organization"]] = contextvars.ContextVar(
    "current_tenant", default=None
)
_current_organization_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "current_organization_id", default=None
)


def get_current_tenant() -> Optional["Organization"]:
    """Get the current tenant from context."""
    return _current_tenant.get()


def get_current_organization_id() -> Optional[int]:
    """Get the current organization ID from context."""
    return _current_organization_id.get()


def set_current_tenant(tenant: Optional["Organization"]) -> None:
    """Set the current tenant in context."""
    _current_tenant.set(tenant)
    if tenant:
        _current_organization_id.set(tenant.id)
    else:
        _current_organization_id.set(None)


def set_current_organization_id(organization_id: Optional[int]) -> None:
    """Set the current organization ID in context."""
    _current_organization_id.set(organization_id)


class TenantContext:
    """
    Tenant context manager for explicit tenant setting.

    Usage:
        async with TenantContext(organization_id=1):
            # All queries within this block will be scoped to org 1
            users = await user_service.get_all()
    """

    def __init__(
        self,
        organization_id: Optional[int] = None,
        tenant: Optional["Organization"] = None
    ):
        self.organization_id = organization_id
        self.tenant = tenant
        self._token_id: Optional[contextvars.Token] = None
        self._token_tenant: Optional[contextvars.Token] = None

    def __enter__(self):
        if self.organization_id is not None:
            self._token_id = _current_organization_id.set(self.organization_id)
        if self.tenant is not None:
            self._token_tenant = _current_tenant.set(self.tenant)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._token_id is not None:
            _current_organization_id.reset(self._token_id)
        if self._token_tenant is not None:
            _current_tenant.reset(self._token_tenant)

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Middleware to resolve and set the current tenant for each request.

    Tenant resolution order:
    1. JWT token (for authenticated requests)
    2. X-Tenant-ID header (for API clients)
    3. Subdomain (for portal requests)
    4. Custom domain lookup (for white-label portals)
    """

    # Paths that don't require tenant resolution
    EXEMPT_PATHS = [
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/onboarding",
        "/api/v1/platform",  # Platform owner endpoints
        "/api/v1/provisioning",  # Provisioning endpoints (router setup)
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    # Portal paths that require subdomain/domain resolution
    PORTAL_PATHS = [
        "/api/v1/portal/hotspot",
        "/api/v1/portal/pppoe",
    ]

    def __init__(self, app, db_session_factory=None):
        super().__init__(app)
        self.db_session_factory = db_session_factory

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request and resolve tenant."""
        # Skip tenant resolution for CORS preflight requests (OPTIONS)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check if path is exempt from tenant resolution
        path = request.url.path

        # Skip tenant resolution for exempt paths
        if any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
            return await call_next(request)

        # Try to resolve tenant
        organization_id = await self._resolve_tenant(request)

        if organization_id:
            set_current_organization_id(organization_id)

            # Optionally load full tenant object for portal paths
            if any(path.startswith(portal) for portal in self.PORTAL_PATHS):
                tenant = await self._load_tenant(organization_id)
                if tenant:
                    set_current_tenant(tenant)
                else:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "Organization not found"}
                    )

        try:
            response = await call_next(request)
            return response
        finally:
            # Clear tenant context after request
            set_current_tenant(None)
            set_current_organization_id(None)

    async def _resolve_tenant(self, request: Request) -> Optional[int]:
        """
        Resolve the tenant from the request.

        Returns:
            Organization ID if found, None otherwise
        """
        # 1. Try JWT token (organization_id claim)
        organization_id = await self._resolve_from_jwt(request)
        if organization_id:
            return organization_id

        # 2. Try X-Tenant-ID header
        tenant_header = request.headers.get("X-Tenant-ID")
        if tenant_header:
            try:
                return int(tenant_header)
            except ValueError:
                # Try as UUID
                organization_id = await self._resolve_from_uuid(tenant_header)
                if organization_id:
                    return organization_id

        # 3. Try subdomain
        organization_id = await self._resolve_from_subdomain(request)
        if organization_id:
            return organization_id

        # 4. Try custom domain
        organization_id = await self._resolve_from_custom_domain(request)
        if organization_id:
            return organization_id

        return None

    async def _resolve_from_jwt(self, request: Request) -> Optional[int]:
        """Extract organization_id from JWT token."""
        from app.core.security import verify_token

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ")[1]
        try:
            token_data = verify_token(token, token_type="access")
            if token_data and hasattr(token_data, "organization_id"):
                return token_data.organization_id
        except Exception:
            pass

        return None

    async def _resolve_from_subdomain(self, request: Request) -> Optional[int]:
        """
        Resolve organization from subdomain.

        Expected format: org-slug.ispbilling.com
        """
        from app.core.config import settings

        host = request.headers.get("Host", "")
        base_domain = getattr(settings, "portal_base_domain", "ispbilling.com")

        if not host or base_domain not in host:
            return None

        # Extract subdomain
        subdomain = host.replace(f".{base_domain}", "").split(":")[0]

        if not subdomain or subdomain in ["www", "api", "app"]:
            return None

        # Look up organization by slug
        return await self._lookup_by_slug(subdomain)

    async def _resolve_from_custom_domain(self, request: Request) -> Optional[int]:
        """
        Resolve organization from custom domain.

        Looks up portal_domain in organizations table.
        """
        host = request.headers.get("Host", "").split(":")[0]
        if not host:
            return None

        return await self._lookup_by_domain(host)

    async def _resolve_from_uuid(self, uuid_str: str) -> Optional[int]:
        """Resolve organization from UUID."""
        if not self.db_session_factory:
            return None

        try:
            from sqlalchemy import select
            from app.models.organization import Organization

            uuid_obj = UUID(uuid_str)

            async with self.db_session_factory() as session:
                result = await session.execute(
                    select(Organization.id).where(Organization.uuid == uuid_obj)
                )
                row = result.scalar_one_or_none()
                return row
        except Exception:
            return None

    async def _lookup_by_slug(self, slug: str) -> Optional[int]:
        """Look up organization ID by slug."""
        if not self.db_session_factory:
            return None

        try:
            from sqlalchemy import select
            from app.models.organization import Organization

            async with self.db_session_factory() as session:
                result = await session.execute(
                    select(Organization.id).where(Organization.slug == slug)
                )
                return result.scalar_one_or_none()
        except Exception:
            return None

    async def _lookup_by_domain(self, domain: str) -> Optional[int]:
        """Look up organization ID by custom domain."""
        if not self.db_session_factory:
            return None

        try:
            from sqlalchemy import select
            from app.models.organization import Organization

            async with self.db_session_factory() as session:
                result = await session.execute(
                    select(Organization.id).where(Organization.portal_domain == domain)
                )
                return result.scalar_one_or_none()
        except Exception:
            return None

    async def _load_tenant(self, organization_id: int) -> Optional["Organization"]:
        """Load full organization object."""
        if not self.db_session_factory:
            return None

        try:
            from sqlalchemy import select
            from app.models.organization import Organization, OrganizationStatus

            async with self.db_session_factory() as session:
                result = await session.execute(
                    select(Organization).where(
                        Organization.id == organization_id,
                        Organization.status.in_([
                            OrganizationStatus.ACTIVE,
                            OrganizationStatus.TRIAL
                        ])
                    )
                )
                return result.scalar_one_or_none()
        except Exception:
            return None
