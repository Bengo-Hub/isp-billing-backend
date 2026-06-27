"""Auth-api branding client — centralized tenant branding source.

auth-api is the single source of truth for tenant IDENTITY + BRANDING (logo_url,
brand_colors, etc.). isp-billing stores NO local branding anymore; the captive
portal config (app/api/v1/portal/hotspot.py) fetches branding SERVER-SIDE from
auth-api's PUBLIC tenant-by-slug endpoint and projects it through its OWN
portal-config response. That keeps the pre-auth captive device pointed only at
the already-walled-gardened isp-billing host (it must NOT call auth-api directly,
which is not reachable behind the walled garden pre-auth).

Endpoint (public, no auth):
    GET {auth_api_base}/api/v1/tenants/by-slug/{slug}

Branding-relevant response fields (auth-api PublicTenantResponse):
    name, slug, logo_url (str|null),
    brand_colors (object: { primary, secondary, accent }).

This client is best-effort: any failure (auth-api down, slug not found, timeout)
returns None so the caller can fall back to a safe default (the org name) and the
captive flow never breaks. Results are cached in-process for a short TTL per slug
to avoid hammering auth-api on every captive page load.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# Simple in-process TTL cache: slug -> (expires_at_monotonic, branding_dict|None).
# A None payload is cached too (negative cache) so a missing/unreachable tenant
# does not trigger an auth-api call on every single captive page load.
_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


def _cache_get(slug: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    entry = _CACHE.get(slug)
    if entry is None:
        return False, None
    expires_at, value = entry
    if time.monotonic() >= expires_at:
        _CACHE.pop(slug, None)
        return False, None
    return True, value


def _cache_set(slug: str, value: Optional[Dict[str, Any]]) -> None:
    ttl = max(0, int(settings.auth_branding_cache_ttl))
    _CACHE[slug] = (time.monotonic() + ttl, value)


def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Map auth-api's PublicTenantResponse → the branding shape the portal uses.

    auth-api exposes ``logo_url`` (string) and ``brand_colors`` (object with
    ``primary`` / ``secondary`` / ``accent``). The captive portal config wants a
    flat ``logo_url`` + ``primary_color`` (and exposes name/title/description from
    the tenant name where auth has no dedicated portal-title column)."""
    colors = payload.get("brand_colors") or {}
    if not isinstance(colors, dict):
        colors = {}

    name = payload.get("name")
    return {
        "name": name,
        "logo_url": payload.get("logo_url"),
        "primary_color": colors.get("primary"),
        "secondary_color": colors.get("secondary"),
        # auth-api has no dedicated portal title/description; the tenant name is
        # the canonical display label, and the portal config falls back to it.
        "portal_title": name,
        "portal_description": None,
    }


async def get_tenant_branding(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch centralized branding for a tenant slug from auth-api (cached).

    Returns the normalized branding dict, or None when auth-api is unreachable /
    the tenant is unknown / nothing is configured. Never raises."""
    slug = (slug or "").strip().lower()
    if not slug:
        return None

    hit, cached = _cache_get(slug)
    if hit:
        return cached

    base = settings.auth_api_base
    if not base:
        logger.debug("auth branding: no auth_api_base configured — skipping fetch")
        _cache_set(slug, None)
        return None

    url = f"{base}/api/v1/tenants/by-slug/{slug}"
    try:
        async with httpx.AsyncClient(timeout=settings.auth_request_timeout) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code == 404:
            logger.info("auth branding: tenant slug %s not found in auth-api", slug)
            _cache_set(slug, None)
            return None
        resp.raise_for_status()
        branding = _normalize(resp.json())
        _cache_set(slug, branding)
        return branding
    except Exception as exc:  # best-effort: never break the captive flow
        logger.warning("auth branding: fetch failed for slug %s: %s", slug, exc)
        # Negative-cache so a flaky auth-api isn't hit on every page load.
        _cache_set(slug, None)
        return None
