"""
IP Bindings Management API.

Manages MikroTik hotspot IP bindings (MAC↔IP static associations).
Bindings are read/written directly to routers — no local DB cache.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_technician_or_admin
from app.database import get_db
from app.models.user import User
from app.modules.routers import RouterService

logger = logging.getLogger(__name__)

router = APIRouter()


# --------------- Schemas ---------------

class IPBindingResponse(BaseModel):
    id: str = Field(..., description="MikroTik .id for this binding")
    address: Optional[str] = Field(None, description="IP address")
    mac_address: Optional[str] = Field(None, description="MAC address")
    to_address: Optional[str] = Field(None, description="Translated IP (NAT)")
    server: Optional[str] = Field(None, description="Hotspot server name")
    type: str = Field("regular", description="Binding type: regular | bypassed | blocked")
    comment: Optional[str] = None
    disabled: bool = False


class IPBindingCreate(BaseModel):
    address: Optional[str] = Field(None, description="IP address to bind")
    mac_address: Optional[str] = Field(None, description="MAC address to bind")
    to_address: Optional[str] = Field(None, description="Translate-to IP address")
    server: Optional[str] = Field(None, description="Hotspot server (blank = all)")
    type: str = Field("regular", pattern="^(regular|bypassed|blocked)$")
    comment: Optional[str] = None
    disabled: bool = False


class IPBindingUpdate(BaseModel):
    address: Optional[str] = None
    mac_address: Optional[str] = None
    to_address: Optional[str] = None
    server: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(regular|bypassed|blocked)$")
    comment: Optional[str] = None
    disabled: Optional[bool] = None


# --------------- Helpers ---------------

def _get_org_id(user: User) -> int:
    return user.organization_id


def _parse_binding(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a raw MikroTik binding dict to our schema keys."""
    return {
        "id": raw.get(".id", ""),
        "address": raw.get("address", ""),
        "mac_address": raw.get("mac-address", ""),
        "to_address": raw.get("to-address", ""),
        "server": raw.get("server", "all"),
        "type": raw.get("type", "regular"),
        "comment": raw.get("comment", ""),
        "disabled": raw.get("disabled", "false") == "true",
    }


async def _get_router_and_connect(db, router_id: int, org_id: int):
    """Resolve router, get credentials, connect, return (client, connection, router)."""
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    service = RouterService(db, organization_id=org_id)
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No credentials for this router")

    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port,
    )
    if not connection:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")

    return client, connection, router_obj


# --------------- Endpoints ---------------

@router.get("/{router_id}", response_model=List[IPBindingResponse])
async def list_ip_bindings(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
):
    """List all hotspot IP bindings on a router."""
    client, connection, _ = await _get_router_and_connect(db, router_id, _get_org_id(current_user))
    try:
        raw = await client.execute_command(connection, "/ip/hotspot/ip-binding", method="get")
        return [_parse_binding(b) for b in (raw or [])]
    finally:
        await client.disconnect(connection)


@router.post("/{router_id}", response_model=IPBindingResponse, status_code=status.HTTP_201_CREATED)
async def create_ip_binding(
    router_id: int,
    data: IPBindingCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Create a new IP binding on a router."""
    if not data.address and not data.mac_address:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of address or mac_address is required",
        )

    client, connection, _ = await _get_router_and_connect(db, router_id, _get_org_id(current_user))
    try:
        params: Dict[str, str] = {"type": data.type}
        if data.address:
            params["address"] = data.address
        if data.mac_address:
            params["mac-address"] = data.mac_address
        if data.to_address:
            params["to-address"] = data.to_address
        if data.server:
            params["server"] = data.server
        if data.comment:
            params["comment"] = data.comment
        if data.disabled:
            params["disabled"] = "true"

        result = await client.execute_command(
            connection, "/ip/hotspot/ip-binding", method="add", **params
        )

        # Re-fetch to return the full object
        all_bindings = await client.execute_command(connection, "/ip/hotspot/ip-binding", method="get")
        # Find the newly created one (last entry or match by returned id)
        new_id = result if isinstance(result, str) else None
        for b in reversed(all_bindings or []):
            if new_id and b.get(".id") == new_id:
                return _parse_binding(b)
            if b.get("address") == data.address and b.get("mac-address") == (data.mac_address or ""):
                return _parse_binding(b)

        # Fallback: return last binding
        if all_bindings:
            return _parse_binding(all_bindings[-1])

        return IPBindingResponse(id="*new", address=data.address, mac_address=data.mac_address, type=data.type)
    finally:
        await client.disconnect(connection)


@router.patch("/{router_id}/{binding_id}", response_model=IPBindingResponse)
async def update_ip_binding(
    router_id: int,
    binding_id: str,
    data: IPBindingUpdate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing IP binding."""
    client, connection, _ = await _get_router_and_connect(db, router_id, _get_org_id(current_user))
    try:
        params: Dict[str, str] = {}
        if data.address is not None:
            params["address"] = data.address
        if data.mac_address is not None:
            params["mac-address"] = data.mac_address
        if data.to_address is not None:
            params["to-address"] = data.to_address
        if data.server is not None:
            params["server"] = data.server
        if data.type is not None:
            params["type"] = data.type
        if data.comment is not None:
            params["comment"] = data.comment
        if data.disabled is not None:
            params["disabled"] = "true" if data.disabled else "false"

        await client.execute_command(
            connection, "/ip/hotspot/ip-binding", method="set",
            id=binding_id, **params
        )

        # Re-fetch the specific binding
        all_bindings = await client.execute_command(connection, "/ip/hotspot/ip-binding", method="get")
        for b in (all_bindings or []):
            if b.get(".id") == binding_id:
                return _parse_binding(b)

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Binding not found after update")
    finally:
        await client.disconnect(connection)


@router.delete("/{router_id}/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ip_binding(
    router_id: int,
    binding_id: str,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Remove an IP binding from a router."""
    client, connection, _ = await _get_router_and_connect(db, router_id, _get_org_id(current_user))
    try:
        await client.execute_command(
            connection, "/ip/hotspot/ip-binding", method="remove", id=binding_id
        )
    finally:
        await client.disconnect(connection)
