"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from app.api.v1 import auth, billing, notifications, plans, routers, subscriptions, users, reports, configuration, mpesa
from app.core.config import settings
from app.core.database import init_db
from app.core.logging import setup_logging
from app.services.initialization_service import initialization_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events."""
    # Startup
    setup_logging()
    
    # Initialize database
    await init_db()
    
    # Auto-initialize system (configurations, admin user)
    encryption_key = getattr(settings, 'encryption_key', 'default-encryption-key-change-in-production')
    await initialization_service.initialize_all(
        database_url=settings.database_url,
        encryption_key=encryption_key
    )
    
    yield
    # Shutdown
    pass


# Security scheme for JWT authentication
security_scheme = HTTPBearer()

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="ISP Billing System API - Comprehensive billing platform for ISPs",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
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
    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/api/v1/auth/login",
                    "scopes": {}
                }
            },
            "description": "OAuth2 password flow - use 'admin' / 'admin123' for testing"
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
        "/api/v1/auth/verify-email", "/api/v1/auth/verify-phone"
    }
    
    # Add security requirements to protected endpoints
    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            if method in ["get", "post", "put", "patch", "delete"]:
                endpoint = openapi_schema["paths"][path][method]
                
                # Only add security to protected endpoints
                if path not in public_paths and "security" not in endpoint:
                    # Use OAuth2PasswordBearer as primary (for Swagger UI), BearerAuth as fallback
                    endpoint["security"] = [
                        {"OAuth2PasswordBearer": []},
                        {"BearerAuth": []}
                    ]
    
    # Add custom info for better API documentation
    openapi_schema["info"]["contact"] = {
        "name": "ISP Billing System Support",
        "email": "support@ispbilling.com",
        "url": "https://github.com/your-org/isp-billing-system"
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
            "url": "https://api.yourdomain.com",
            "description": "Production server"
        }
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add trusted host middleware for production
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*.yourdomain.com", "yourdomain.com"]
    )


# Include API routers using the consolidated v1 router
from app.api.v1 import api_router
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root() -> JSONResponse:
    """Root endpoint."""
    return JSONResponse(
        content={
            "message": f"Welcome to {settings.app_name}",
            "version": settings.app_version,
            "environment": settings.environment,
            "docs_url": "/docs" if settings.debug else None,
        }
    )


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
