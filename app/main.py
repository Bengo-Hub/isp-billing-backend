"""FastAPI application entry point."""

import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.seed_service import run_startup_seeds
from app.core.tenant_middleware import TenantMiddleware
from app.core.licence_middleware import LicenceEnforcementMiddleware
from app.core.database import AsyncSessionLocal
from app.modules.system import initialization_service

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID for tracing."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.trace_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events."""
    # Startup
    setup_logging()
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")

    # Verify database connection (schema managed by Alembic)
    await init_db()

    # Run idempotent seeds (RBAC roles/permissions, platform admin, settings, tiers)
    await run_startup_seeds()

    # Get encryption key from settings (no more hardcoded fallback in production)
    encryption_key = settings.encryption_key or settings.master_password
    if not encryption_key and settings.is_production:
        logger.error("No encryption key configured for production!")
        raise RuntimeError("ENCRYPTION_KEY or MASTER_PASSWORD required in production")

    # Use a development default only in non-production
    if not encryption_key:
        logger.warning("Using development encryption key - NOT FOR PRODUCTION")
        encryption_key = "dev-only-key-do-not-use-in-production"

    # Auto-initialize system configurations
    await initialization_service.initialize_all(
        database_url=settings.database_url,
        encryption_key=encryption_key
    )

    logger.info("Application startup complete")
    yield

    # Shutdown
    logger.info("Application shutting down")
    pass


# Security scheme for JWT authentication
security_scheme = HTTPBearer()

# Create FastAPI application
# Docs are always enabled for API documentation access
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="ISP Billing System API - Comprehensive billing platform for ISPs",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Authentication", "description": "User authentication and authorization"},
        {"name": "Users", "description": "User management operations"},
        {"name": "Routers", "description": "Router management operations"},
        {"name": "Service Plans", "description": "Service plan management"},
        {"name": "Subscriptions", "description": "Customer subscription management"},
        {"name": "Billing & Payments", "description": "Billing and payment operations"},
        {"name": "Notifications & Support", "description": "Notification and support ticket management"},
        {"name": "Reports & Analytics", "description": "Reports and analytics with file export capabilities"},
        {"name": "Platform - Organizations", "description": "ISP provider management (Platform Owner only)"},
        {"name": "Platform - Billing", "description": "Platform billing and invoices (Platform Owner only)"},
        {"name": "Platform - Analytics", "description": "Platform-wide analytics (Platform Owner only)"},
        {"name": "Platform - Subscription Tiers", "description": "Subscription tier management (Platform Owner only)"},
        {"name": "Portal - Hotspot", "description": "Hotspot customer portal for package purchase and vouchers"},
        {"name": "Portal - PPPoE", "description": "PPPoE customer portal for usage and subscription management"},
        {"name": "Tenant - Payment Gateways", "description": "Payment gateway configuration for ISP providers"},
        {"name": "Tenant - Settings", "description": "Organization settings for ISP providers"},
        {"name": "Onboarding", "description": "ISP provider signup and registration"},
    ],
)

# Add security scheme to OpenAPI
app.openapi_schema = None  # Clear cache to regenerate with security

def custom_openapi():
    """Custom OpenAPI schema with JWT security and OAuth2 password flow."""
    if app.openapi_schema:
        return app.openapi_schema
    
    from fastapi.openapi.utils import get_openapi
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add OAuth2 password bearer security scheme for Swagger UI integration
    # In production, hide demo credentials
    demo_description = (
        "**OAuth2 Password Flow**\n\n"
        "Use your username/email and password to authenticate.\n\n"
        "**Note**: You can use either username OR email in the username field."
    ) if settings.is_production else (
        "**OAuth2 Password Flow - Demo Credentials:**\n\n"
        "**Demo Admin Account:**\n"
        "- Username: `demo`\n"
        "- Password: `demo123`\n"
        "- Email: `demo@codevertexitsolutions.com`\n"
        "- Role: Admin (ISP Provider)\n\n"
        "**Superuser Account:**\n"
        "- Username: `superuser`\n"
        "- Password: `superuser123`\n"
        "- Email: `superuser@codevertexitsolutions.com`\n"
        "- Role: Superuser (Full System Access)\n\n"
        "**Note**: You can use either username OR email in the username field."
    )

    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/api/v1/auth/login",
                    "scopes": {},
                }
            },
            "description": demo_description
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Manual JWT token entry (get token from /api/v1/auth/login)"
        }
    }
    
    # Define public endpoints that don't require authentication
    public_paths = {
        "/", "/health", "/docs", "/redoc", "/openapi.json",
        "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh",
        "/api/v1/auth/verify", "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password",
        "/api/v1/auth/verify-email", "/api/v1/auth/verify-phone",
        "/api/v1/platform/tiers/public",
    }

    # Portal and onboarding endpoints are public (access without JWT)
    public_path_prefixes = [
        "/api/v1/portal/hotspot/",
        "/api/v1/portal/pppoe/",
        "/api/v1/onboarding/",
    ]
    
    # Add default examples to login endpoint
    if "/api/v1/auth/login" in openapi_schema["paths"]:
        login_endpoint = openapi_schema["paths"]["/api/v1/auth/login"]["post"]
        
        # Add example request body with default credentials
        if "requestBody" in login_endpoint:
            login_endpoint["requestBody"]["content"]["application/x-www-form-urlencoded"]["example"] = {
                "username": "demo",
                "password": "demo123"
            }
            
            # Add multiple examples
            login_endpoint["requestBody"]["content"]["application/x-www-form-urlencoded"]["examples"] = {
                "demo_admin": {
                    "summary": "Demo Admin Account",
                    "description": "ISP Provider demo account with admin permissions",
                    "value": {
                        "username": "demo",
                        "password": "demo123"
                    }
                },
                "demo_admin_email": {
                    "summary": "Demo Admin (using email)",
                    "description": "Login using email instead of username",
                    "value": {
                        "username": "demo@codevertexitsolutions.com",
                        "password": "demo123"
                    }
                },
                "superuser": {
                    "summary": "Superuser Account",
                    "description": "Full system access for advanced configuration",
                    "value": {
                        "username": "superuser",
                        "password": "superuser123"
                    }
                }
            }
    
    # Add security requirements to protected endpoints
    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            if method in ["get", "post", "put", "patch", "delete"]:
                endpoint = openapi_schema["paths"][path][method]

                # Check if path is public
                is_public = path in public_paths
                if not is_public:
                    for prefix in public_path_prefixes:
                        if path.startswith(prefix):
                            is_public = True
                            break

                # Only add security to protected endpoints
                if not is_public and "security" not in endpoint:
                    # Use OAuth2PasswordBearer as primary (for Swagger UI), BearerAuth as fallback
                    endpoint["security"] = [
                        {"OAuth2PasswordBearer": []},
                        {"BearerAuth": []}
                    ]
    
    # Add custom info for better API documentation
    openapi_schema["info"]["contact"] = {
        "name": "ISP Billing System Support",
        "email": "support@ispbilling.com",
        "url": "https://github.com/Bengo-Hub/isp-billing-backend"
    }
    
    openapi_schema["info"]["license"] = {
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT"
    }
    
    # Add server information
    openapi_schema["servers"] = [
        {
            "url": "http://localhost:8000",
            "description": "Development server"
        },
        {
            "url": "https://192.168.100.4:8000",
            "description": "Network Development server"
        },
        {
            "url": "https://ispbillingapi.codevertexitsolutions.com",
            "description": "Production server"
        }
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Register custom exception handlers
register_exception_handlers(app)

# Middleware order: last added = outermost (runs first on request).
# CORS must be outermost so it adds headers to ALL responses, including errors.

# Add request ID middleware for tracing (innermost)
app.add_middleware(RequestIDMiddleware)

# Add tenant middleware for multi-tenancy support (needs DB for slug/UUID/domain lookups)
app.add_middleware(TenantMiddleware, db_session_factory=AsyncSessionLocal)

# Add licence enforcement middleware (runs after tenant middleware resolves org)
app.add_middleware(LicenceEnforcementMiddleware, db_session_factory=AsyncSessionLocal)

# Add trusted host middleware for production
if settings.is_production and settings.allowed_hosts:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts.split(",")
    )

# Add CORS middleware (outermost - must wrap everything so headers are always present)
cors_origins = settings.cors_origins if settings.is_production else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Include API routers using the consolidated v1 router
from app.api.v1 import api_router
app.include_router(api_router, prefix="/api/v1")

# Mount static files for uploaded content (logos, etc.)
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles

_static_dir = Path(__file__).resolve().parent.parent / "static" / "uploads"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_static_dir)), name="uploads")


@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint - redirects to Swagger UI documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(
        content={
            "status": "healthy",
            "version": settings.app_version,
            "environment": settings.environment,
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=1 if settings.debug else settings.workers,
    )
