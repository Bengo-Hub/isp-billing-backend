"""Integration URL configuration API endpoints.

Provides endpoints for:
- Retrieving auto-configured URLs for integrations
- Getting URLs for specific integrations
"""

from typing import Dict, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.url_config import URLConfigService, get_url_config_service

router = APIRouter(prefix="/urls", tags=["Integration URLs"])


class IntegrationUrlsResponse(BaseModel):
    """Response schema for all integration URLs."""

    backend_base: str
    frontend_base: str
    urls: Dict[str, Dict[str, str]]


class IntegrationUrlsForIntegration(BaseModel):
    """Response schema for specific integration URLs."""

    base_url: str
    urls: Dict[str, str]


class HealthCheckResponse(BaseModel):
    """Response for health check endpoints."""

    status: str
    connected: bool
    message: Optional[str] = None


@router.get(
    "/",
    response_model=IntegrationUrlsResponse,
    summary="Get all auto-configured integration URLs",
    description="""
    Retrieves all auto-configured URLs for all supported integrations.
    
    URLs are automatically resolved based on:
    - BACKEND_URL and FRONTEND_URL environment variables
    - CORS origins (development fallback)
    - Environment detection (HTTPS forced in production)
    
    Use these URLs when configuring webhooks and callbacks in external services.
    """,
)
async def get_all_integration_urls(
    backend_url: Optional[str] = Query(
        None,
        description="Override backend base URL for URL generation",
    ),
    frontend_url: Optional[str] = Query(
        None,
        description="Override frontend base URL for URL generation",
    ),
) -> IntegrationUrlsResponse:
    """Get all auto-configured integration URLs."""
    service = URLConfigService(
        backend_url=backend_url,
        frontend_url=frontend_url,
    )
    result = service.get_all_integration_urls()
    return IntegrationUrlsResponse(
        backend_base=result["backend_base"],
        frontend_base=result["frontend_base"],
        urls=result["urls"],
    )


@router.get(
    "/{integration}",
    response_model=IntegrationUrlsForIntegration,
    summary="Get URLs for a specific integration",
    description="""
    Retrieves all auto-configured URLs for a specific integration.
    
    Supported integrations:
    - mpesa: M-PESA payment gateway
    - paystack: Paystack payment gateway
    - kopokopo: Kopo Kopo payments
    - pesapal: PesaPal payments
    """,
)
async def get_integration_urls(
    integration: str,
    backend_url: Optional[str] = Query(
        None,
        description="Override backend base URL",
    ),
    frontend_url: Optional[str] = Query(
        None,
        description="Override frontend base URL",
    ),
) -> IntegrationUrlsForIntegration:
    """Get URLs for a specific integration."""
    service = URLConfigService(
        backend_url=backend_url,
        frontend_url=frontend_url,
    )
    urls = service.get_integration_urls(integration)
    base_url = urls.pop("base_url", service.get_backend_url())
    return IntegrationUrlsForIntegration(
        base_url=base_url,
        urls=urls,
    )
