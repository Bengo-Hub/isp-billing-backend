"""Resolve whether an ISP provider (tenant) may still sell to its end customers.

End customers buying hotspot/PPPoE packages must be blocked when the PROVIDER's
OWN subscription has fully lapsed (past the grace window) — surfaced to the
customer as a neutral "service temporarily unavailable, contact your provider"
message (with the provider's contact details), never as billing/suspension
wording aimed at the customer.

Fail-OPEN by design: we never block a paying end customer because of OUR
uncertainty (no central tenant link, subscriptions-api unreachable, or no
subscription on file). We only return blocked when we positively know the
provider is blocked:
  - the platform suspended the org (Organization.status == SUSPENDED), or
  - subscriptions-api reports access_status == "blocked" (expired past grace).

Note: a provider in the GRACE window (access_status == "grace") is still allowed
to sell — grace keeps them operational while they renew.
"""
import logging
from typing import Any, Dict, Tuple

from app.models.organization import Organization, OrganizationStatus

logger = logging.getLogger(__name__)


def provider_contact(org: Organization) -> Dict[str, Any]:
    """Public contact card so customers can reach the provider to restore service."""
    return {
        "name": org.name,
        "phone": org.phone or org.notification_phone,
        "email": org.email or org.notification_email,
        "whatsapp": org.notification_phone or org.phone,
        "address": org.address,
        "city": org.city,
    }


async def resolve_provider_access(organization: Organization) -> Tuple[bool, Dict[str, Any]]:
    """Return ``(active, contact)`` for the provider.

    ``active`` is False ONLY when we positively know the provider is blocked.
    Everything else (active / trial / grace / unknown / outage) → True.
    """
    contact = provider_contact(organization)

    # Platform-level suspension is authoritative and local — block immediately.
    if organization.status == OrganizationStatus.SUSPENDED:
        return False, contact

    tenant_id = organization.auth_tenant_id
    if not tenant_id:
        return True, contact  # no central link yet → fail-open (allow)

    try:
        from app.services.subscriptions_client import get_subscriptions_client

        sub = await get_subscriptions_client().get_subscription(str(tenant_id))
    except Exception as exc:  # SubscriptionsError / transport — never block on outage
        logger.warning(
            "provider access check failed for tenant %s: %s — allowing (fail-open)",
            tenant_id,
            exc,
        )
        return True, contact

    if not sub:
        return True, contact  # no subscription on file → fail-open

    access = str(sub.get("access_status") or "").strip().lower()
    if access == "blocked":
        return False, contact
    # active / grace / trial / unknown → allow
    return True, contact
