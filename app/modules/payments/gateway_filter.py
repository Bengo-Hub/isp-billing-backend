"""Captive payment-gateway filtering (online-only + essential-config gate).

Single source of truth for deciding which payment gateways are shown to an
end-customer in the captive package-purchase flow. Two independent problems are
solved here, mirroring subscriptions-api's "online-only" payment restriction
(PAYG / collectable billing must transact on online rails only):

Issue 1 — NEVER show cash / cash-on-delivery / manual / offline rails.
    An ISP package payment has no delivery: the customer MUST pay online to get
    internet. Cash-like gateways can't be auto-charged, so they are excluded by
    gateway *type/code* (robust — not a brittle display-name match).

Issue 2 — a 2-layer ACTIVE gate. A gateway is returned as ACTIVE only when BOTH:
    Layer 1  it is enabled (platform-owner enabled AND/OR tenant enabled — the
             caller passes the already-resolved enabled flag), AND
    Layer 2  ALL essential configs it requires are actually present at the
             tenant level (``gateway_essential_configs_complete``). A gateway
             with ``is_active=True`` but missing e.g. the M-Pesa short code /
             passkey is NOT active and is filtered out — selecting it would fail.

Both gates apply to EVERY tenant (platform-owner tenants included) — every
tenant's configs are checked as the layer-2 gate.

This module is intentionally framework-free (no FastAPI / DB imports) so it can
be unit-tested and reused by any code path that lists active gateways.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

# ---------------------------------------------------------------------------
# Gateway type normalisation
# ---------------------------------------------------------------------------

# Cash / offline / manual rails that must NEVER be offered for an ISP package
# payment. Matched against the NORMALISED gateway type/code (lower-cased), so a
# gateway is excluded regardless of its human-facing display name.
CASH_LIKE_GATEWAY_TYPES = frozenset(
    {
        "cash",
        "cash_on_delivery",
        "cod",
        "manual",
        "offline",
        "on_delivery",
        "pay_on_delivery",
        "pay_later",
        "bank_transfer",  # manual reconciliation — not an auto-charge online rail
        "cheque",
        "check",
    }
)


def normalize_gateway_type(gateway_type: Optional[str]) -> str:
    """Lower-case + trim a gateway type/code for robust comparison."""
    return (gateway_type or "").strip().lower()


def is_cash_like_gateway(gateway_type: Optional[str]) -> bool:
    """True when ``gateway_type`` is a cash / COD / manual / offline rail.

    Robust to display-name drift: matches the normalised type/code against the
    cash-like set, plus a substring guard for ``cash`` / ``cod`` variants.
    """
    gt = normalize_gateway_type(gateway_type)
    if not gt:
        return False
    if gt in CASH_LIKE_GATEWAY_TYPES:
        return True
    # Substring guard catches values like "cash_pickup", "mpesa_cod", etc.
    return "cash" in gt or gt == "cod" or gt.endswith("_cod") or "_cod_" in gt


# ---------------------------------------------------------------------------
# Per-gateway required (essential) tenant configs — Layer 2
# ---------------------------------------------------------------------------

# For each ONLINE gateway type, the set of essential config keys that MUST be
# present (non-empty) at the tenant level for the gateway to actually work. If
# any one is missing/blank the gateway is treated as NOT active and is hidden.
#
# Keys are matched case-insensitively and several common aliases are accepted
# per logical field (e.g. ``shortcode`` ~ ``paybill`` ~ ``till_number``) so this
# stays robust to naming differences between the various config stores.
GATEWAY_REQUIRED_CONFIGS: Dict[str, List[List[str]]] = {
    # M-Pesa STK Push (Daraja): needs the business short code (paybill/till),
    # the API consumer key + secret, and the STK passkey.
    "mpesa": [
        ["shortcode", "short_code", "paybill", "paybill_number", "till", "till_number", "public_shortcode"],
        ["consumer_key"],
        ["consumer_secret"],
        ["passkey", "pass_key"],
    ],
    "mpesa_paybill": [
        ["shortcode", "short_code", "paybill", "paybill_number", "public_shortcode"],
        ["consumer_key"],
        ["consumer_secret"],
        ["passkey", "pass_key"],
    ],
    "mpesa_till": [
        ["shortcode", "short_code", "till", "till_number", "public_shortcode"],
        ["consumer_key"],
        ["consumer_secret"],
        ["passkey", "pass_key"],
    ],
    # Paystack: needs at minimum the secret key (public key strongly recommended
    # for inline/checkout). Require the secret key; accept either name for it.
    "paystack": [
        ["secret_key", "paystack_secret_key", "secret"],
    ],
    # Card processing via Paystack-style provider.
    "card": [
        ["secret_key", "paystack_secret_key", "secret"],
    ],
}


def _has_value(value: Any) -> bool:
    """True when a config value is meaningfully present (non-empty)."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _lookup(tenant_config: Mapping[str, Any], aliases: Iterable[str]) -> bool:
    """True when ANY alias resolves to a present value in ``tenant_config``.

    Matching is case-insensitive over the config keys.
    """
    if not tenant_config:
        return False
    lowered = {str(k).lower(): v for k, v in tenant_config.items()}
    for alias in aliases:
        if _has_value(lowered.get(alias.lower())):
            return True
    return False


def gateway_essential_configs_complete(
    gateway: Mapping[str, Any],
    tenant_config: Optional[Mapping[str, Any]],
) -> bool:
    """Return True when ALL essential configs for ``gateway`` are present.

    ``gateway`` must carry a ``gateway_type`` (or ``type``) key. ``tenant_config``
    is the tenant-level config bag for that gateway (e.g. the M-Pesa creds /
    Paystack keys). When the gateway type has no declared required-config set we
    treat it as complete (nothing essential to be missing).
    """
    gw_type = normalize_gateway_type(
        gateway.get("gateway_type") or gateway.get("type")
    )
    required_groups = GATEWAY_REQUIRED_CONFIGS.get(gw_type)
    if not required_groups:
        # No essential-config requirements declared for this type → nothing to
        # gate on (e.g. a future online rail using platform-managed creds only).
        return True

    cfg = tenant_config or {}
    for alias_group in required_groups:
        # Each group is an OR of acceptable aliases for one logical field; every
        # group must be satisfied (AND across groups).
        if not _lookup(cfg, alias_group):
            return False
    return True


# ---------------------------------------------------------------------------
# Combined filter — the one entry point all listing code paths should use
# ---------------------------------------------------------------------------

def filter_captive_payment_gateways(
    gateways: Iterable[Mapping[str, Any]],
    *,
    tenant_configs: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Filter a raw gateway list down to those usable in the captive flow.

    A gateway survives only when ALL hold:
      * it is NOT a cash / COD / manual / offline rail (Issue 1), AND
      * Layer 1 — it is enabled (its ``is_active`` flag is truthy), AND
      * Layer 2 — all its essential tenant configs are present
        (``gateway_essential_configs_complete``).

    ``tenant_configs`` maps a normalised gateway type → that gateway's tenant
    config bag (used for the Layer-2 check). When omitted/empty, Layer 2 still
    runs against an empty bag, so any gateway that declares required configs is
    correctly hidden until configured.

    The surviving gateway dicts are returned unchanged (the caller owns the
    response schema), so existing frontend field contracts stay stable.
    """
    tenant_configs = tenant_configs or {}
    result: List[Dict[str, Any]] = []

    for gw in gateways:
        gw_type = normalize_gateway_type(
            gw.get("gateway_type") or gw.get("type")
        )

        # Issue 1: never offer cash/COD/manual/offline for ISP package payment.
        if is_cash_like_gateway(gw_type):
            continue

        # Layer 1: must be enabled (platform-owner and/or tenant enabled — the
        # caller has already collapsed those into is_active).
        if not _has_value(gw.get("is_active")) or not bool(gw.get("is_active")):
            continue

        # Layer 2: essential tenant configs must all be present.
        cfg = tenant_configs.get(gw_type)
        if not gateway_essential_configs_complete(gw, cfg):
            continue

        result.append(dict(gw))

    return result
