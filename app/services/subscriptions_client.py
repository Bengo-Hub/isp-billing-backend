"""Subscriptions-api S2S client (Phase 3, ADDITIVE).

Thin async httpx wrapper over the central subscriptions-api service-to-service
endpoints, authenticated with a pre-shared key in the ``X-API-Key`` header
(``settings.internal_service_key``).

This is the migration target for isp-billing's local platform-level
licensing: instead of the local ``Licence`` / ``PlatformSubscriptionTier``
models being the source of truth for an ISP provider's plan, the central
subscriptions-api owns the ISP provider tenant's subscription. The local
models remain in place (deprecated, not deleted) until the migration is
complete so the running platform-billing UI is not broken mid-migration.

Confirmed endpoints (subscriptions-api router.go, all under ``/api/v1``):

- ``get_subscription`` → ``GET /api/v1/tenants/{tenant_id}/subscription``
  S2S read of a tenant's resolved subscription. Returns the SubscriptionResult
  shape: ``{plan_code, status, access_status, features: [...],
  limits: {max_routers, max_customers, ...}, usage_limits: {...}, ...}``.
  Accessible via the platform API key (X-API-Key) or a platform-owner JWT.
  This is the same endpoint auth-api calls to enrich JWT ``sub_*`` claims.

- ``subscribe`` → ``POST /api/v1/admin/tenants/{tenant_id}/subscription``
  body ``{"planCode": "<ISP_PLAN_CODE>", "startTrial": bool}`` — upserts the
  tenant's subscription onto the given plan (platform-admin / S2S route).

- ``generate_invoice`` → ``POST /api/v1/admin/tenants/{tenant_id}/subscription/generate-invoice``
  triggers treasury auto-invoicing for the tenant's current subscription.

``tenant_id`` is the ISP provider's per-tenant UUID (``Organization.uuid``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SubscriptionsError(Exception):
    """Raised when a subscriptions-api S2S call fails."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class SubscriptionsClient:
    """Async S2S client for the central subscriptions-api."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.subscriptions_api_url or "").rstrip("/")
        self.api_key = api_key or settings.internal_service_key
        self.timeout = timeout or getattr(settings, "subscriptions_request_timeout", 10.0)

    @property
    def is_configured(self) -> bool:
        """True when the client has the URL + key required to call subscriptions-api."""
        return bool(self.base_url and self.api_key)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def get_subscription(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Read a tenant's resolved subscription (plan / status / features / limits).

        Returns the parsed JSON body, or ``None`` when the client is not
        configured or the tenant has no subscription (404). Never raises for the
        "not subscribed yet" case — callers treat ``None`` as "no info, allow"
        during migration. Transport / 5xx errors raise ``SubscriptionsError``.
        """
        if not self.is_configured:
            return None

        url = f"{self.base_url}/api/v1/tenants/{tenant_id}/subscription"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                raise SubscriptionsError(
                    f"subscriptions request failed: {exc}"
                ) from exc

        if resp.status_code == 404:
            return None
        return self._decode(resp)

    async def subscribe(
        self,
        tenant_id: str,
        plan_code: str,
        *,
        start_trial: bool = False,
        generate_invoice: bool = False,
    ) -> Dict[str, Any]:
        """Subscribe (upsert) a tenant onto an ISP plan by plan code.

        Calls the platform-admin S2S route; with ``generate_invoice=True`` it
        also asks subscriptions-api to raise the treasury invoice for the new
        subscription period (treasury auto-invoicing).
        """
        if not self.is_configured:
            raise SubscriptionsError(
                "subscriptions client not configured "
                "(subscriptions_api_url / internal_service_key)"
            )

        url = f"{self.base_url}/api/v1/admin/tenants/{tenant_id}/subscription"
        body = {"planCode": plan_code, "startTrial": start_trial}
        result = await self._post(url, body)

        if generate_invoice:
            try:
                await self.generate_invoice(tenant_id)
            except SubscriptionsError as exc:
                # Auto-invoicing is best-effort: a subscription was created even
                # if the invoice call failed. Surface as a warning, not a failure.
                logger.warning(
                    "subscription created for tenant %s but invoice generation failed: %s",
                    tenant_id,
                    exc,
                )
        return result

    async def generate_invoice(self, tenant_id: str) -> Dict[str, Any]:
        """Trigger treasury auto-invoicing for the tenant's current subscription."""
        if not self.is_configured:
            raise SubscriptionsError("subscriptions client not configured")

        url = (
            f"{self.base_url}/api/v1/admin/tenants/{tenant_id}"
            f"/subscription/generate-invoice"
        )
        return await self._post(url, {})

    async def _post(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=body, headers=self._headers())
            except httpx.HTTPError as exc:
                raise SubscriptionsError(
                    f"subscriptions request failed: {exc}"
                ) from exc
        return self._decode(resp)

    @staticmethod
    def _decode(resp: httpx.Response) -> Dict[str, Any]:
        if resp.status_code >= 400:
            detail = resp.text
            logger.error(
                "subscriptions-api error %s for %s: %s",
                resp.status_code,
                resp.request.url,
                detail,
            )
            raise SubscriptionsError(
                f"subscriptions-api returned {resp.status_code}: {detail}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise SubscriptionsError(
                f"invalid JSON from subscriptions-api: {exc}"
            ) from exc


def get_subscriptions_client() -> SubscriptionsClient:
    """Factory for a subscriptions client bound to current settings."""
    return SubscriptionsClient()
