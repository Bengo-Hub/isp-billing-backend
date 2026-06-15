"""Shared treasury top-up intent helper.

Centralizes the "create an invoice-first treasury payment intent + build the
shared pay-page checkout URL" flow used by the local BILLING top-up paths that
were migrated off the removed local payment gateways:

    - SMS-credit top-up (admin/sms_credit.py, tenant/messages.py)
    - WhatsApp-subscription top-up (platform/whatsapp.py)
    - PPPoE renewal (portal/pppoe.py)

Treasury-api is the single payment path (mirrors the hotspot purchase flow):
the intent is created under the ISP tenant's UUID with source_service="isp" so
treasury attributes + settles the revenue. Confirmation is by the caller polling
treasury get_status (or the NATS consumer) — there is NO local-gateway fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.services.treasury_client import TreasuryClient, TreasuryError

logger = logging.getLogger(__name__)


@dataclass
class TopUpIntentResult:
    """Result of creating a treasury top-up intent."""

    intent_id: str
    checkout_url: str
    initiate_url: Optional[str] = None


async def create_topup_intent(
    *,
    tenant_uuid: str,
    amount: str,
    currency: str,
    reference: str,
    reference_type: str,
    description: str,
    redirect_url: str,
    customer_email: Optional[str] = None,
    customer_phone: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    button_text: Optional[str] = None,
) -> Optional[TopUpIntentResult]:
    """Create a treasury intent and build its pay-page checkout URL.

    Returns ``None`` when treasury is unusable (not configured / call failed /
    no intent id); the caller surfaces an error. There is no local fallback.
    """
    client = TreasuryClient()
    if not client.is_configured:
        logger.error(
            "treasury client not configured (treasury_api_url / internal_service_key)"
            " — cannot process %s payment", reference_type,
        )
        return None

    try:
        intent = await client.create_payment_intent(
            tenant=tenant_uuid,
            amount=amount,
            currency=currency,
            reference_id=reference,
            reference_type=reference_type,
            source_service="isp",
            description=description,
            idempotency_key=reference,
            customer_email=customer_email,
            customer_phone=customer_phone,
            callback_url=redirect_url,
            metadata=metadata,
        )
    except TreasuryError as exc:
        logger.error("treasury create_payment_intent failed for %s: %s", reference, exc)
        return None

    intent_id = intent.get("intent_id") or intent.get("id")
    if not intent_id:
        logger.error("treasury intent response missing intent_id: %s", intent)
        return None

    checkout_url = client.build_pay_page_url(
        tenant=tenant_uuid,
        intent_id=str(intent_id),
        amount=amount,
        currency=currency,
        reference_id=reference,
        reference_type=reference_type,
        redirect_url=redirect_url,
        description=description,
        initiate_url=intent.get("initiate_url"),
        button_text=button_text,
    )

    return TopUpIntentResult(
        intent_id=str(intent_id),
        checkout_url=checkout_url,
        initiate_url=intent.get("initiate_url"),
    )


async def get_intent_status(*, tenant_uuid: str, intent_id: str) -> Optional[str]:
    """Return the lowercased treasury intent status, or ``None`` on error / unconfigured."""
    client = TreasuryClient()
    if not client.is_configured:
        return None
    try:
        intent = await client.get_status(tenant=tenant_uuid, intent_id=intent_id)
    except TreasuryError as exc:
        logger.error("treasury get_status failed for intent %s: %s", intent_id, exc)
        return None
    return str(intent.get("status", "")).lower()


SUCCESS_STATUSES = {"succeeded", "success", "completed", "paid"}
FAILURE_STATUSES = {"failed", "cancelled", "canceled", "expired"}
