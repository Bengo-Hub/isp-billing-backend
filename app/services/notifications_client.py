"""Central notifications-api S2S client (Phase 4, ADDITIVE / FLAGGED).

Thin async httpx wrapper over the central notifications-api REST send endpoint,
authenticated with a pre-shared key in the ``X-API-Key`` header
(``settings.internal_service_key``).

This is the migration target for isp-billing's notification DELIVERY: instead of
calling the local SMS / WhatsApp / email providers directly, delivery is routed
to the central notifications-api which owns provider selection (Africa's Talking
default for SMS, Meta WhatsApp Cloud API for WhatsApp), templating, and delivery
logging.

IMPORTANT — this moves DELIVERY only. The local SMS-credit accounting
(``app/models/sms_credit.py`` + ``SMSSendingService`` billing) and the local
WhatsApp-subscription billing (``app/models/whatsapp.py``) remain the source of
truth for what an ISP provider is charged. This client is invoked only for the
actual send, after the local billing/credit checks have run.

Endpoint (see shared-docs/notifications-rest-api-integration.md):

    POST {base_url}/{tenant_id}/notifications/messages
    headers: X-API-Key: <internal_service_key>
    body: {
        "channel":  "sms" | "whatsapp" | "email" | "push",
        "template": "ispbilling/<name>",   # without channel prefix
        "to":       ["+2547..."],
        "data":     { ...template variables... },
        "metadata": { "subject": "...", "provider": "..." }   # optional
    }

Returns ``202 Accepted`` with ``{status, requestId}``.

Gated by ``settings.use_central_notifications`` at the call sites; this client
additionally no-ops (``is_configured == False``) when URL / key are missing so a
misconfiguration degrades to the existing direct-provider path rather than
raising.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class NotificationsError(Exception):
    """Raised when a notifications-api S2S call fails."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class NotificationsClient:
    """Async S2S client for the central notifications-api send endpoint."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        tenant_id: Optional[str] = None,
    ):
        self.base_url = (base_url or settings.notifications_api_url or "").rstrip("/")
        self.api_key = api_key or settings.internal_service_key
        self.timeout = timeout or getattr(settings, "notifications_request_timeout", 10.0)
        self.default_tenant_id = tenant_id or getattr(settings, "notifications_tenant_id", None)

    @property
    def is_configured(self) -> bool:
        """True when the client has the URL + key required to call notifications-api."""
        return bool(self.base_url and self.api_key)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def send(
        self,
        *,
        channel: str,
        template: str,
        to: List[str],
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """POST a notification to the central notifications-api send endpoint.

        Args:
            channel: ``sms`` | ``whatsapp`` | ``email`` | ``push``.
            template: template path WITHOUT channel prefix, e.g.
                ``ispbilling/payment_receipt``.
            to: list of recipients (phone numbers / emails / device tokens).
            data: template variables.
            metadata: optional ``subject`` (email), ``provider`` override, etc.
            tenant_id: per-request tenant id; falls back to the configured default.
            idempotency_key: optional dedup key (24h window).

        Returns:
            The parsed JSON response (``{status, requestId}``) on success, or
            ``None`` when the client is not configured. Raises
            ``NotificationsError`` on transport / non-2xx errors so callers can
            fall back to the local direct-provider path.
        """
        if not self.is_configured:
            logger.debug("notifications client not configured; skipping central send")
            return None

        resolved_tenant = tenant_id or self.default_tenant_id
        if not resolved_tenant:
            raise NotificationsError(
                "notifications send requires a tenant_id "
                "(pass tenant_id= or set notifications_tenant_id)"
            )

        url = f"{self.base_url}/{resolved_tenant}/notifications/messages"
        body: Dict[str, Any] = {
            "channel": channel,
            "template": template,
            "to": to,
            "data": data or {},
        }
        if metadata:
            body["metadata"] = metadata

        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise NotificationsError(
                    f"notifications request failed: {exc}"
                ) from exc

        return self._decode(resp)

    @staticmethod
    def _decode(resp: httpx.Response) -> Dict[str, Any]:
        if resp.status_code >= 400:
            detail = resp.text
            logger.error(
                "notifications-api error %s for %s: %s",
                resp.status_code,
                resp.request.url,
                detail,
            )
            raise NotificationsError(
                f"notifications-api returned {resp.status_code}: {detail}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError:
            # 202 with empty body is acceptable.
            return {"status": "accepted"}


def get_notifications_client() -> NotificationsClient:
    """Factory for a notifications client bound to current settings."""
    return NotificationsClient()
