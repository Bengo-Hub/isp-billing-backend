import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_sms_credit_routes_exist(app_client: AsyncClient):
    # Smoke-test that routes are wired; auth is handled by fixtures if available
    # Listing accounts should require admin; expect 401/403 or 200 depending on fixture setup
    resp = await app_client.get("/api/v1/sms-credit/accounts")
    assert resp.status_code in (200, 401, 403)


@pytest.mark.asyncio
async def test_routers_active_connections_route(app_client: AsyncClient):
    # Without a valid router id this should be 404 or 401/403
    resp = await app_client.get("/api/v1/routers/999999/active-connections")
    assert resp.status_code in (401, 403, 404)


