"""Routers API endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_technician_or_admin, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.router import RouterStatus, RouterType
from app.schemas.router import (
    Router, RouterCreate, RouterUpdate, RouterList, RouterStats, RouterLog,
    RouterSyncRequest, RouterSyncResponse, RouterDevice, RouterDeviceCreate, RouterDeviceUpdate
)
from app.services.router_service import RouterService

router = APIRouter()


@router.get("/", response_model=RouterList)
async def get_routers(
    pagination: PaginationParams = Depends(),
    status: Optional[RouterStatus] = Query(None),
    router_type: Optional[RouterType] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterList:
    """Get all routers with pagination and filters."""
    service = RouterService(db)
    result = await service.get_all(
        pagination=pagination,
        status=status,
        router_type=router_type,
        search=search,
    )
    return RouterList(**result)


@router.post("/", response_model=Router, status_code=status.HTTP_201_CREATED)
async def create_router(
    router_data: RouterCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Router:
    """Create a new router."""
    service = RouterService(db)
    try:
        router = await service.create_router(
            name=router_data.name,
            ip_address=router_data.ip_address,
            username=router_data.username,
            password=router_data.password,
            router_type=router_data.router_type,
            port=router_data.port,
            location=router_data.location,
            description=router_data.description,
        )
        return router
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{router_id}", response_model=Router)
async def get_router(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Router:
    """Get router by ID."""
    service = RouterService(db)
    router = await service.get_by_id(router_id)
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found"
        )
    return router


@router.patch("/{router_id}", response_model=Router)
async def update_router(
    router_id: int,
    router_data: RouterUpdate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Router:
    """Update router."""
    service = RouterService(db)
    router = await service.update_router(router_id, router_data.dict(exclude_unset=True))
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found"
        )
    return router


@router.delete("/{router_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_router(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete router."""
    service = RouterService(db)
    try:
        success = await service.delete_router(router_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Router not found"
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{router_id}/sync", response_model=RouterSyncResponse)
async def sync_router(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterSyncResponse:
    """Sync router status with MikroTik."""
    service = RouterService(db)
    success = await service.sync_router_status(router_id)
    
    if success:
        router = await service.get_by_id(router_id)
        return RouterSyncResponse(
            success=True,
            message="Router synced successfully",
            router_id=router_id,
            status=router.status.value if router else None,
            uptime=router.uptime if router else None,
            last_seen=router.last_seen if router else None,
        )
    else:
        return RouterSyncResponse(
            success=False,
            message="Failed to sync router",
            router_id=router_id,
        )


@router.post("/sync-all", response_model=Dict[str, Any])
async def sync_all_routers(
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Sync all routers."""
    service = RouterService(db)
    result = await service.sync_all_routers()
    return result


@router.get("/{router_id}/stats", response_model=RouterStats)
async def get_router_stats(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterStats:
    """Get router statistics."""
    service = RouterService(db)
    stats = await service.get_router_usage_stats(router_id)
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found"
        )
    return RouterStats(**stats)


@router.get("/{router_id}/logs", response_model=List[RouterLog])
async def get_router_logs(
    router_id: int,
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[RouterLog]:
    """Get router operation logs."""
    service = RouterService(db)
    logs = await service.get_router_logs(router_id, limit)
    return logs


@router.get("/{router_id}/devices", response_model=List[RouterDevice])
async def get_router_devices(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[RouterDevice]:
    """Get devices connected to router."""
    service = RouterService(db)
    devices = await service.get_router_devices(router_id)
    return devices


@router.post("/{router_id}/devices/sync", response_model=Dict[str, str])
async def sync_router_devices(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Sync devices from MikroTik router."""
    service = RouterService(db)
    success = await service.sync_router_devices(router_id)
    
    if success:
        return {"message": "Devices synced successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to sync devices"
        )


# Router Device Management
@router.post("/{router_id}/devices", response_model=RouterDevice, status_code=status.HTTP_201_CREATED)
async def create_router_device(
    router_id: int,
    device_data: RouterDeviceCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterDevice:
    """Create a new router device."""
    service = RouterService(db)
    # Check if router exists
    router = await service.get_by_id(router_id)
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found"
        )
    
    # Create device
    device = await service.create_router_device(router_id, device_data.dict())
    return device


@router.patch("/devices/{device_id}", response_model=RouterDevice)
async def update_router_device(
    device_id: int,
    device_data: RouterDeviceUpdate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterDevice:
    """Update a router device."""
    service = RouterService(db)
    device = await service.update_router_device(device_id, device_data.dict(exclude_unset=True))
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    return device


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_router_device(
    device_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Delete a router device."""
    service = RouterService(db)
    success = await service.delete_router_device(device_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )


@router.get("/{router_id}/devices", response_model=List[RouterDevice])
async def get_router_devices(
    router_id: int,
    status: Optional[str] = Query(None),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[RouterDevice]:
    """Get devices for a router."""
    service = RouterService(db)
    devices = await service.get_router_devices(router_id, status)
    return devices


@router.get("/{router_id}/active-connections", response_model=List[Dict[str, Any]])
async def get_active_connections(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get active hotspot and PPPoE connections directly from MikroTik."""
    from app.integrations.mikrotik import MikroTikAPI
    service = RouterService(db)
    router = await service.get_by_id(router_id)
    if not router:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    api = MikroTikAPI(router)
    connected = await api.connect()
    if not connected:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    try:
        connections = await api.get_active_connections()
        return connections
    finally:
        await api.disconnect()


@router.post("/{router_id}/disconnect-user")
async def disconnect_user(
    router_id: int,
    username: str,
    user_type: str = Query("hotspot", pattern="^(hotspot|pppoe)$"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Disable a hotspot or PPPoE user on the router (soft disconnect)."""
    from app.integrations.mikrotik import MikroTikAPI
    service = RouterService(db)
    router = await service.get_by_id(router_id)
    if not router:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    api = MikroTikAPI(router)
    connected = await api.connect()
    if not connected:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    try:
        ok = await api.disable_user(username=username, user_type=user_type)
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to disconnect user")
        return {"message": "User disconnected", "username": username, "type": user_type}
    finally:
        await api.disconnect()


@router.get("/devices/{device_id}", response_model=RouterDevice)
async def get_router_device(
    device_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterDevice:
    """Get a router device by ID."""
    service = RouterService(db)
    device = await service.get_router_device(device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    return device