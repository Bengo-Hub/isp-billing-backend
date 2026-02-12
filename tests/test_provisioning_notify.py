import pytest
from datetime import datetime
from app.core.security import create_access_token
from app.services.ping_monitor import ping_monitor


async def test_provisioning_notify_records_pending_checkin(client, admin_headers, db_session):
    # Create a provisioning token (type: provisioning)
    token_data = {"sub": "1", "type": "provisioning", "permissions": ["provisioning.execute"]}
    token = create_access_token(token_data)

    # Call notify endpoint with a fake IP
    response = await client.post(f"/api/v1/provisioning/bootstrap/notify?token={token}&identity=UnitTest&ip_address=10.10.10.10")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["session_id"] is None
    assert body["note"] == "pending_checkin_recorded"

    # Ensure ping_monitor pending checkin recorded
    assert "10.10.10.10" in ping_monitor.pending_checkins
    info = ping_monitor.pending_checkins["10.10.10.10"]
    assert info.get("identity") == "UnitTest" or "timestamp" in info
