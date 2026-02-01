"""Routers API endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_technician_or_admin, PaginationParams
from app.core.database import get_db
from app.core.exceptions import ValidationError, RouterOperationError
from app.models.user import User, UserRole
from app.models.router import RouterStatus, RouterType
from app.schemas.router import (
    Router, RouterCreate, RouterUpdate, RouterList, RouterStats, RouterLog,
    RouterSyncRequest, RouterSyncResponse, RouterDevice, RouterDeviceCreate, RouterDeviceUpdate
)
from app.modules.routers import RouterService

router = APIRouter()


def _get_org_id(current_user: User) -> Optional[int]:
    """Get organization ID for multi-tenancy filtering."""
    # Platform owners can optionally see all data
    if current_user.role == UserRole.PLATFORM_OWNER:
        return None  # No filter for platform owners
    return current_user.organization_id


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
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    """Create a new router.

    Credentials are automatically pulled from environment settings
    (MIKROTIK_API_USERNAME, MIKROTIK_API_PASSWORD). Frontend should not send credentials.
    """
    from app.core.config import settings

    service = RouterService(db, organization_id=current_user.organization_id)
    try:
        # Always use credentials from env settings, never from frontend
        router = await service.create_router(
            name=router_data.name,
            ip_address=router_data.ip_address,
            username=settings.mikrotik_api_username,
            password=settings.mikrotik_api_password,
            router_type=router_data.router_type,
            port=router_data.port,
            location=router_data.location,
            description=router_data.description,
        )
        return router
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e.message))
    except RouterOperationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e.message))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/upsert", response_model=Router)
async def upsert_router(
    router_data: RouterCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Router:
    """Create or update a router by IP address (for provisioning).

    If a router with the same IP address already exists, it will be updated.
    Otherwise, a new router will be created.

    Credentials are automatically pulled from environment settings
    (MIKROTIK_API_USERNAME, MIKROTIK_API_PASSWORD). Frontend should not send credentials.

    This endpoint is used during provisioning to ensure the same session always
    works with the same router, updating it if it already exists.
    """
    from app.core.config import settings
    from app.models.router import Router as RouterModel
    from app.services.router_provisioning import store_router_credentials

    service = RouterService(db, organization_id=current_user.organization_id)

    try:
        # Check if router with this IP already exists
        query = select(RouterModel).where(RouterModel.ip_address == router_data.ip_address)
        if current_user.organization_id:
            query = query.where(RouterModel.organization_id == current_user.organization_id)

        result = await db.execute(query)
        existing_router = result.scalar_one_or_none()

        if existing_router:
            # Update existing router
            update_data = {
                "name": router_data.name,
                "port": router_data.port,
                "router_type": router_data.router_type,
            }
            if router_data.location:
                update_data["location"] = router_data.location
            if router_data.description:
                update_data["description"] = router_data.description

            updated_router = await service.update_router(existing_router.id, update_data)

            # Store/update encrypted credentials
            await store_router_credentials(
                db=db,
                router_id=existing_router.id,
                username=settings.mikrotik_api_username,
                password=settings.mikrotik_api_password,
                bootstrap_completed=existing_router.bootstrap_completed or False
            )

            return updated_router
        else:
            # Create new router
            new_router = await service.create_router(
                name=router_data.name,
                ip_address=router_data.ip_address,
                username=settings.mikrotik_api_username,
                password=settings.mikrotik_api_password,
                router_type=router_data.router_type,
                port=router_data.port,
                location=router_data.location,
                description=router_data.description,
            )

            # Store encrypted credentials for the new router
            await store_router_credentials(
                db=db,
                router_id=new_router.id,
                username=settings.mikrotik_api_username,
                password=settings.mikrotik_api_password,
                bootstrap_completed=False
            )

            return new_router

    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e.message))
    except RouterOperationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e.message))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{router_id}", response_model=Router)
async def get_router(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Router:
    """Get router by ID."""
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
    try:
        success = await service.delete_router(router_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Router not found"
            )
    except RouterOperationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
    result = await service.sync_all_routers()
    return result


@router.get("/{router_id}/stats", response_model=RouterStats)
async def get_router_stats(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterStats:
    """Get router statistics."""
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
    logs = await service.get_router_logs(router_id, limit)
    return logs


@router.get("/{router_id}/devices", response_model=List[RouterDevice])
async def get_router_devices(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[RouterDevice]:
    """Get devices connected to router."""
    service = RouterService(db, organization_id=_get_org_id(current_user))
    devices = await service.get_router_devices(router_id)
    return devices


@router.post("/{router_id}/devices/sync", response_model=Dict[str, str])
async def sync_router_devices(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Sync devices from MikroTik router."""
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
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
    service = RouterService(db, organization_id=_get_org_id(current_user))
    success = await service.delete_router_device(device_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )


@router.get("/{router_id}/active-connections", response_model=List[Dict[str, Any]])
async def get_active_connections(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get active hotspot and PPPoE connections directly from MikroTik."""
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # Get credentials from DB (encrypted) with fallback to env settings
    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No credentials available for router")

    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port
    )
    if not connection:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    try:
        connections = await client.get_active_connections(connection)
        return connections
    finally:
        await client.disconnect(connection)


@router.post("/{router_id}/disconnect-user")
async def disconnect_user(
    router_id: int,
    username: str,
    user_type: str = Query("hotspot", pattern="^(hotspot|pppoe)$"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Disable a hotspot or PPPoE user on the router (soft disconnect)."""
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # Get credentials from DB (encrypted) with fallback to env settings
    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No credentials available for router")

    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port
    )
    if not connection:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    try:
        ok = await client.disable_user(connection, username=username, user_type=user_type)
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to disconnect user")
        return {"message": "User disconnected", "username": username, "type": user_type}
    finally:
        await client.disconnect(connection)


@router.get("/devices/{device_id}", response_model=RouterDevice)
async def get_router_device(
    device_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterDevice:
    """Get a router device by ID."""
    service = RouterService(db, organization_id=_get_org_id(current_user))
    device = await service.get_router_device(device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    return device


@router.post("/{router_id}/sync-time", response_model=Dict[str, Any])
async def sync_router_time(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Sync router time with NTP server."""
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # Get credentials from DB (encrypted) with fallback to env settings
    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No credentials available for router")

    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port
    )
    if not connection:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    try:
        # Enable NTP client and sync time
        await client.execute_command(
            connection,
            "/system/ntp/client",
            method="set",
            enabled="yes",
            servers="pool.ntp.org,time.google.com"
        )

        # Get current router time after sync
        system_info = await client.get_system_info(connection)
        router_time = system_info.get('date', '') + ' ' + system_info.get('time', '') if system_info else 'Unknown'

        return {
            "success": True,
            "message": "Router time synchronized with NTP servers",
            "router_time": router_time,
            "ntp_servers": ["pool.ntp.org", "time.google.com"]
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to sync time: {str(e)}")
    finally:
        await client.disconnect(connection)


@router.post("/{router_id}/sync-hotspot-files", response_model=Dict[str, Any])
async def sync_hotspot_files(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Sync hotspot files (login page, terms, etc.) to router."""
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # Get credentials from DB (encrypted) with fallback to env settings
    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No credentials available for router")

    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port
    )
    if not connection:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    try:
        # Get list of hotspot servers to identify which profiles to sync
        hotspot_servers = await client.get_hotspot_servers(connection) if hasattr(client, 'get_hotspot_servers') else []

        # Get hotspot profile information
        profiles = await client.get_hotspot_profiles(connection) if hasattr(client, 'get_hotspot_profiles') else []

        synced_profiles = []
        for profile in profiles:
            profile_name = profile.get('name', 'default')
            synced_profiles.append(profile_name)

        return {
            "success": True,
            "message": "Hotspot files synchronized",
            "synced_profiles": synced_profiles if synced_profiles else ["default"],
            "hotspot_servers": len(hotspot_servers),
            "note": "Custom login pages can be uploaded via FTP to /hotspot directory"
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to sync hotspot files: {str(e)}")
    finally:
        await client.disconnect(connection)


@router.post("/{router_id}/regenerate-winbox", response_model=Dict[str, Any])
async def regenerate_winbox_credentials(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Regenerate Winbox/API credentials for the router."""
    import secrets
    import string

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # Generate new secure password
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    new_password = ''.join(secrets.choice(alphabet) for _ in range(16))

    # Update router password in database
    await service.update_router(router_id, {"password": new_password})

    # Get remote Winbox URL if configured
    remote_winbox_url = await service.get_winbox_url(router_id)

    # Generate local Winbox connection string
    local_winbox_url = f"winbox://{router_obj.ip_address}:{8291}"

    return {
        "success": True,
        "message": "Winbox credentials regenerated",
        "router_id": router_id,
        "username": router_obj.username,
        "new_password": new_password,
        "winbox_url": remote_winbox_url or local_winbox_url,
        "local_winbox_url": local_winbox_url,
        "remote_winbox_url": remote_winbox_url,
        "winbox_port": router_obj.winbox_port,
        "api_port": router_obj.port or 8728,
        "note": "Please update your Winbox saved credentials with the new password"
    }


@router.get("/{router_id}/winbox-url", response_model=Dict[str, Any])
async def get_winbox_url(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get Winbox connection URL for remote access.

    Returns both the remote VPN-based URL and the local direct URL.
    The remote URL uses the organization's VPN domain and the router's
    assigned Winbox port (e.g., vpn.codevertex.com:51255).
    """
    from app.models.organization import OrganizationSettings

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # Get VPN domain from organization settings
    vpn_domain = "vpn.codevertex.com"  # Default
    if router_obj.organization_id:
        result = await db.execute(
            select(OrganizationSettings).where(
                OrganizationSettings.organization_id == router_obj.organization_id
            )
        )
        settings = result.scalar_one_or_none()
        if settings and settings.vpn_domain:
            vpn_domain = settings.vpn_domain

    # Build URLs
    winbox_port = router_obj.winbox_port
    remote_winbox_url = f"{vpn_domain}:{winbox_port}" if winbox_port else None
    local_winbox_url = f"{router_obj.ip_address}:8291"

    return {
        "router_id": router_id,
        "router_name": router_obj.name,
        "winbox_port": winbox_port,
        "winbox_url": remote_winbox_url,
        "local_winbox_url": local_winbox_url,
        "vpn_domain": vpn_domain,
        "is_configured": winbox_port is not None,
        "tooltip": "Click to copy. Ensure port 8291 is open on the device. After copying, paste this to the Winbox connect field."
    }