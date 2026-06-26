"""
Treasury-api S2S client (Phase 2, ADDITIVE).

Thin async httpx wrapper over the central treasury-api service-to-service
payment endpoints, authenticated with a pre-shared key in the ``X-API-Key``
header (``settings.internal_service_key``). This is only exercised when
``settings.use_treasury_payments`` is True; the existing direct-gateway
(Paystack / M-PESA) flow remains the default and the fallback.

Contract (mirrors ordering-backend's treasury client + shared-docs/payment-workflow.md):

- ``create_payment_intent`` → ``POST /api/v1/s2s/{tenant}/payments/intents``
  Body uses ``payment_method: "pending"`` (invoice-first): treasury creates the
  intent WITHOUT initiating a gateway and returns ``intent_id`` (+ ``initiate_url``).
  The customer is then sent to the shared pay page to pick a gateway.
- ``initiate`` → ``POST /api/v1/pay/{tenant}/intents/{intentID}/initiate``
  (public route) fires the chosen provider for an existing intent.
- ``get_status`` → ``GET /api/v1/s2s/{tenant}/payments/intents/{intentID}``
  returns the full intent; its ``status`` field is what the poller reads
  (``pending`` | ``processing`` | ``succeeded`` | ``failed`` | ``cancelled`` | ``expired``).

``tenant`` is the ISP's per-tenant UUID (``Organization.uuid``). Because the
intent is created under that tenant with ``source_service="isp"``, treasury
attributes the revenue to that ISP and settles it to them via its own
payout/settlement subsystem (Paystack transfer recipients / M-PESA B2C).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TreasuryError(Exception):
    """Raised when a treasury-api S2S call fails."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class TreasuryClient:
    """Async S2S client for treasury-api payment intents."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        pay_page_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.treasury_api_url or "").rstrip("/")
        self.api_key = api_key or settings.internal_service_key
        self.pay_page_url = (
            pay_page_url or settings.treasury_pay_page_url or ""
        ).rstrip("/")
        self.timeout = timeout or settings.treasury_request_timeout

    @property
    def is_configured(self) -> bool:
        """True when the client has the URL + key required to call treasury."""
        return bool(self.base_url and self.api_key)

    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def create_payment_intent(
        self,
        *,
        tenant: str,
        amount: str,
        currency: str,
        reference_id: str,
        reference_type: str = "hotspot_purchase",
        source_service: str = "isp",
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create an invoice-first (``payment_method="pending"``) payment intent.

        ``amount`` is passed as a string so it is serialised exactly (treasury
        decodes it into a shopspring decimal). Returns the parsed JSON body,
        which includes ``intent_id`` and (for pending intents) ``initiate_url``.
        """
        if not self.is_configured:
            raise TreasuryError(
                "treasury client not configured (treasury_api_url / internal_service_key)"
            )

        url = f"{self.base_url}/api/v1/s2s/{tenant}/payments/intents"
        body: Dict[str, Any] = {
            "reference_id": reference_id,
            "reference_type": reference_type,
            "payment_method": "pending",
            "currency": currency,
            "amount": amount,
            "source_service": source_service,
        }
        if description:
            body["description"] = description
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        if customer_email:
            body["customer_email"] = customer_email
        if customer_phone:
            body["phone_number"] = customer_phone
        if callback_url:
            body["callback_url"] = callback_url
        if metadata:
            body["metadata"] = metadata

        return await self._post(url, body, idempotency_key=idempotency_key)

    async def initiate(
        self,
        *,
        tenant: str,
        intent_id: str,
        payment_method: str,
        customer_email: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initiate payment for an existing intent (public pay route).

        Optional: only needed if isp-billing initiates a specific gateway
        server-side instead of handing the customer to the shared pay page.
        """
        if not self.is_configured:
            raise TreasuryError("treasury client not configured")

        url = f"{self.base_url}/api/v1/pay/{tenant}/intents/{intent_id}/initiate"
        body: Dict[str, Any] = {"payment_method": payment_method}
        if customer_email:
            body["customer_email"] = customer_email
        if phone_number:
            body["phone_number"] = phone_number
        return await self._post(url, body)

    async def list_active_gateways(self, *, tenant: str) -> List[Dict[str, Any]]:
        """List the tenant's ACTIVE selected payment gateways (S2S).

        Calls ``GET /api/v1/s2s/{tenant}/gateways/selected`` (INTERNAL_SERVICE_KEY
        auth). Treasury owns gateway enable-state, so this is the Layer-1 source
        of truth for which gateways are platform+tenant enabled. Each item is a
        gateway dict carrying at least ``gateway_type`` / ``is_active`` /
        ``is_primary`` (NO credentials — treasury never exposes secrets).

        Returns ``[]`` (never raises) when treasury is unconfigured / the call
        fails, so callers degrade gracefully rather than 500-ing the public
        captive page.
        """
        if not self.is_configured:
            return []

        url = f"{self.base_url}/api/v1/s2s/{tenant}/gateways/selected"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, headers=self._headers())
            data = self._decode(resp)
        except (httpx.HTTPError, TreasuryError) as exc:
            logger.warning("treasury list_active_gateways failed for %s: %s", tenant, exc)
            return []

        # Treasury wraps the list as {"selected": [...]}; be defensive about shape.
        items = data.get("selected") or data.get("gateways") or []
        if not isinstance(items, list):
            return []
        return [g for g in items if isinstance(g, dict)]

    async def get_status(self, *, tenant: str, intent_id: str) -> Dict[str, Any]:
        """Fetch the current payment intent (its ``status`` field is canonical).

        Treasury has no dedicated ``/status`` sub-route — GET on the intent
        returns the full object whose ``status`` is what callers poll.
        """
        if not self.is_configured:
            raise TreasuryError("treasury client not configured")

        url = f"{self.base_url}/api/v1/s2s/{tenant}/payments/intents/{intent_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                raise TreasuryError(f"treasury request failed: {exc}") from exc
        return self._decode(resp)

    def build_pay_page_url(
        self,
        *,
        tenant: str,
        intent_id: str,
        amount: str,
        currency: str,
        reference_id: str,
        reference_type: str,
        redirect_url: str,
        description: Optional[str] = None,
        initiate_url: Optional[str] = None,
        button_text: Optional[str] = None,
    ) -> str:
        """Build the shared treasury-ui pay page URL the customer is sent to.

        Mirrors the query contract in shared-docs/payment-workflow.md. The
        ``redirect_url`` should point back at isp-billing's own callback page so
        the Phase-0 captive-device login flow still runs after payment.
        """
        from urllib.parse import urlencode

        params = {
            "tenant": tenant,
            "intent_id": intent_id,
            "amount": amount,
            "currency": currency,
            "reference_id": reference_id,
            "reference_type": reference_type,
            "redirect_url": redirect_url,
        }
        if description:
            params["description"] = description
        if initiate_url:
            params["initiate_url"] = initiate_url
        if button_text:
            params["button_text"] = button_text
        # The canonical treasury pay page is `{books-ui}/pay`. Be defensive about
        # how pay_page_url is configured: strip a trailing slash AND a trailing
        # `/pay` so a value like ".../pay" (a common misconfig) doesn't produce the
        # broken `/pay/pay` (404). Append exactly one `/pay`.
        base = self.pay_page_url.rstrip("/")
        if base.lower().endswith("/pay"):
            base = base[:-4]
        return f"{base}/pay?{urlencode(params)}"

    async def _post(
        self,
        url: str,
        body: Dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    url, json=body, headers=self._headers(idempotency_key)
                )
            except httpx.HTTPError as exc:
                raise TreasuryError(f"treasury request failed: {exc}") from exc
        return self._decode(resp)

    @staticmethod
    def _decode(resp: httpx.Response) -> Dict[str, Any]:
        if resp.status_code >= 400:
            detail = resp.text
            logger.error(
                "treasury-api error %s for %s: %s",
                resp.status_code,
                resp.request.url,
                detail,
            )
            raise TreasuryError(
                f"treasury-api returned {resp.status_code}: {detail}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise TreasuryError(f"invalid JSON from treasury-api: {exc}") from exc


def get_treasury_client() -> TreasuryClient:
    """Factory for a treasury client bound to current settings."""
    return TreasuryClient()
