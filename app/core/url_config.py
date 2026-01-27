"""URL Configuration Service for automatic URL resolution.

This module provides centralized URL management for webhooks, callbacks,
and public links across all environments (development, staging, production).

Based on ERP URLConfigService pattern for consistent URL handling.
"""

import os
from functools import lru_cache
from typing import Dict, Optional
from urllib.parse import urljoin

from app.core.config import get_settings


class URLConfigService:
    """Service for managing and auto-configuring integration URLs.
    
    Provides methods to:
    - Generate webhook and callback URLs for integrations
    - Resolve frontend/backend base URLs from environment
    - Ensure HTTPS in production environments
    - Support URL overrides from database settings
    """

    # Default paths for various integrations
    DEFAULT_PATHS = {
        "mpesa": {
            "stk_callback": "/api/v1/integrations/mpesa/stk-callback/",
            "b2c_result": "/api/v1/integrations/mpesa/b2c-result/",
            "b2c_timeout": "/api/v1/integrations/mpesa/b2c-timeout/",
            "validation": "/api/v1/integrations/mpesa/validation/",
            "confirmation": "/api/v1/integrations/mpesa/confirmation/",
        },
        "paystack": {
            "webhook": "/api/v1/integrations/paystack/webhook/",
            "callback": "/api/v1/integrations/paystack/callback/",
            "redirect": "/payments/verify",  # Frontend redirect
        },
        "africastalking": {
            "delivery_report": "/api/v1/integrations/sms/africastalking/delivery/",
            "incoming": "/api/v1/integrations/sms/africastalking/incoming/",
        },
        "twilio": {
            "status_callback": "/api/v1/integrations/sms/twilio/status/",
            "incoming": "/api/v1/integrations/sms/twilio/incoming/",
        },
        "kopokopo": {
            "webhook": "/api/v1/integrations/kopokopo/webhook/",
            "callback": "/api/v1/integrations/kopokopo/callback/",
        },
        "pesapal": {
            "ipn": "/api/v1/integrations/pesapal/ipn/",
            "callback": "/api/v1/integrations/pesapal/callback/",
            "redirect": "/payments/verify",  # Frontend redirect
        },
    }

    def __init__(
        self,
        backend_url: Optional[str] = None,
        frontend_url: Optional[str] = None,
        force_https: bool = False,
    ):
        """Initialize URL configuration service.
        
        Args:
            backend_url: Override for backend base URL.
            frontend_url: Override for frontend base URL.
            force_https: Force HTTPS for all URLs (typically production).
        """
        self._settings = get_settings()
        self._backend_url = backend_url or self._settings.backend_url
        self._frontend_url = frontend_url or self._settings.frontend_url
        self._force_https = force_https or self._settings.force_https or self._settings.is_production

    def get_backend_url(self) -> str:
        """Get backend base URL from settings or environment.
        
        Priority order:
        1. Constructor override / settings.backend_url
        2. BACKEND_URL environment variable
        3. Settings-based construction (host:port)
        """
        if self._backend_url:
            return self._ensure_https(self._backend_url)

        # Check environment variable
        env_url = os.environ.get("BACKEND_URL")
        if env_url:
            return self._ensure_https(env_url)

        # Construct from settings
        protocol = "https" if self._force_https else "http"
        host = self._settings.host
        port = self._settings.port

        # In production, don't include port if it's 80/443
        if self._settings.is_production and port in (80, 443):
            return f"{protocol}://{host}"

        return f"{protocol}://{host}:{port}"

    def get_frontend_url(self) -> str:
        """Get frontend base URL from settings or environment.
        
        Priority order:
        1. Constructor override
        2. FRONTEND_URL environment variable
        3. First CORS origin (development fallback)
        """
        if self._frontend_url:
            return self._ensure_https(self._frontend_url)

        # Check environment variable
        env_url = os.environ.get("FRONTEND_URL")
        if env_url:
            return self._ensure_https(env_url)

        # Use first CORS origin as fallback
        if self._settings.cors_origins:
            return self._ensure_https(self._settings.cors_origins[0])

        return "http://localhost:3000"

    def _ensure_https(self, url: str) -> str:
        """Ensure URL uses HTTPS in production environments.
        
        Args:
            url: URL to potentially upgrade to HTTPS.
            
        Returns:
            URL with HTTPS if in production, otherwise unchanged.
        """
        if not self._force_https:
            return url.rstrip("/")

        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)

        return url.rstrip("/")

    def get_webhook_url(
        self,
        integration: str,
        endpoint: str,
        override_base_url: Optional[str] = None,
    ) -> str:
        """Get full webhook URL for an integration.
        
        Args:
            integration: Integration name (e.g., 'mpesa', 'paystack').
            endpoint: Endpoint name (e.g., 'stk_callback', 'webhook').
            override_base_url: Optional override for base URL.
            
        Returns:
            Full webhook URL.
            
        Raises:
            ValueError: If integration or endpoint is not defined.
        """
        base_url = override_base_url or self.get_backend_url()
        path = self._get_path(integration, endpoint)
        return urljoin(base_url + "/", path.lstrip("/"))

    def get_callback_url(
        self,
        integration: str,
        endpoint: str,
        is_frontend: bool = False,
        override_base_url: Optional[str] = None,
    ) -> str:
        """Get full callback URL for an integration.
        
        Args:
            integration: Integration name.
            endpoint: Endpoint name.
            is_frontend: If True, use frontend base URL (for user redirects).
            override_base_url: Optional override for base URL.
            
        Returns:
            Full callback URL.
        """
        if is_frontend:
            base_url = override_base_url or self.get_frontend_url()
        else:
            base_url = override_base_url or self.get_backend_url()

        path = self._get_path(integration, endpoint)
        return urljoin(base_url + "/", path.lstrip("/"))

    def _get_path(self, integration: str, endpoint: str) -> str:
        """Get path for integration endpoint.
        
        Args:
            integration: Integration name (case-insensitive).
            endpoint: Endpoint name (case-insensitive).
            
        Returns:
            Path for the endpoint.
            
        Raises:
            ValueError: If integration or endpoint is not defined.
        """
        integration_lower = integration.lower()
        endpoint_lower = endpoint.lower()

        if integration_lower not in self.DEFAULT_PATHS:
            raise ValueError(
                f"Unknown integration: {integration}. "
                f"Available: {list(self.DEFAULT_PATHS.keys())}"
            )

        endpoints = self.DEFAULT_PATHS[integration_lower]
        if endpoint_lower not in endpoints:
            raise ValueError(
                f"Unknown endpoint '{endpoint}' for integration '{integration}'. "
                f"Available: {list(endpoints.keys())}"
            )

        return endpoints[endpoint_lower]

    def get_all_integration_urls(self) -> Dict[str, Dict[str, str]]:
        """Get all integration URLs organized by integration name.
        
        Returns:
            Nested dict: {integration: {endpoint: full_url}}
        """
        result = {
            "backend_base": self.get_backend_url(),
            "frontend_base": self.get_frontend_url(),
            "urls": {},
        }

        for integration, endpoints in self.DEFAULT_PATHS.items():
            result["urls"][integration] = {}
            for endpoint, path in endpoints.items():
                # Determine if this is a frontend redirect path
                is_frontend = path.startswith("/payments/") or path.startswith("/auth/")
                
                if is_frontend:
                    full_url = urljoin(self.get_frontend_url() + "/", path.lstrip("/"))
                else:
                    full_url = urljoin(self.get_backend_url() + "/", path.lstrip("/"))

                result["urls"][integration][endpoint] = full_url

        return result

    def get_integration_urls(self, integration: str) -> Dict[str, str]:
        """Get all URLs for a specific integration.
        
        Args:
            integration: Integration name.
            
        Returns:
            Dict mapping endpoint names to full URLs.
        """
        all_urls = self.get_all_integration_urls()
        integration_lower = integration.lower()

        if integration_lower not in all_urls["urls"]:
            raise ValueError(f"Unknown integration: {integration}")

        return {
            "base_url": self.get_backend_url(),
            **all_urls["urls"][integration_lower],
        }


@lru_cache()
def get_url_config_service(
    backend_url: Optional[str] = None,
    frontend_url: Optional[str] = None,
) -> URLConfigService:
    """Get cached URL configuration service instance.
    
    Args:
        backend_url: Optional backend URL override.
        frontend_url: Optional frontend URL override.
        
    Returns:
        URLConfigService instance.
    """
    return URLConfigService(
        backend_url=backend_url,
        frontend_url=frontend_url,
    )


def clear_url_config_cache() -> None:
    """Clear the URL config service cache. Useful for testing."""
    get_url_config_service.cache_clear()


# Convenience exports
url_config = URLConfigService()
