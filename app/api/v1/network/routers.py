"""Routers API endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_technician_or_admin,
    PaginationParams,
    enforce_plan_limit,
)
from app.core.config import settings
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


async def _count_routers(db: AsyncSession, organization_id: Optional[int]) -> int:
    """Count existing routers for a tenant — used by the max_routers plan gate.

    organization_id may be None (platform-wide); then all routers are counted.
    """
    from sqlalchemy import func
    from app.models.router import Router as RouterModel

    query = select(func.count()).select_from(RouterModel)
    if organization_id is not None:
        query = query.where(RouterModel.organization_id == organization_id)
    result = await db.execute(query)
    return int(result.scalar() or 0)


async def _queue_agent_action(db: AsyncSession, router_obj, action: str, user_id: Optional[int], extra_query: Optional[dict] = None) -> str:
    """Queue a NAT-safe action for a router via its polling agent.

    The agent downloads a generated per-action .rsc (see /action-script) and
    imports it locally. Returns the queued command id.
    """
    from datetime import timedelta
    from app.core.security import create_access_token
    from app.services.router_agent import RouterAgentService

    token = create_access_token(
        {
            "sub": str(user_id or 0),
            "type": "access",
            "permissions": ["provisioning.execute", "router.configure"],
        },
        expires_delta=timedelta(hours=2),
    )
    base = (settings.backend_url or "").rstrip("/")
    url = f"{base}/api/v1/routers/{router_obj.id}/action-script/{action}?token={token}"
    if extra_query:
        from urllib.parse import urlencode
        url += "&" + urlencode({k: v for k, v in extra_query.items() if v not in (None, "")})
    agent_service = RouterAgentService(db)
    cmd = await agent_service.queue_command(
        router_id=router_obj.id,
        action="fetch_import",
        params={"url": url},
        priority=2,
        source="router_action",
        source_id=action,
    )
    await db.commit()
    return cmd.id


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


@router.post(
    "/",
    response_model=Router,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_plan_limit("max_routers", _count_routers))],
)
async def create_router(
    router_data: RouterCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Router:
    """Create a new router.

    Credentials are automatically pulled from environment settings
    (MIKROTIK_API_USERNAME, MIKROTIK_API_PASSWORD). Frontend should not send credentials.

    Phase 3: gated by the central subscriptions-api ``max_routers`` plan limit
    via ``enforce_plan_limit`` (fail-open during migration; superuser /
    platform-owner bypass).
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
        # Match an existing router by IP OR by NAME within the org. The router's
        # name (identity) is stable across provisions while its IP can change
        # (NAT / WireGuard), so matching by IP alone would miss it and the create
        # path would then violate the unique name constraint ("already exists").
        from sqlalchemy import or_
        match_conds = [RouterModel.ip_address == router_data.ip_address]
        if router_data.name:
            match_conds.append(RouterModel.name == router_data.name)
        query = select(RouterModel).where(or_(*match_conds))
        if current_user.organization_id:
            query = query.where(RouterModel.organization_id == current_user.organization_id)

        result = await db.execute(query)
        existing_router = result.scalars().first()

        if existing_router:
            # Update existing router (refresh IP too — it may have changed).
            update_data = {
                "name": router_data.name,
                "ip_address": router_data.ip_address,
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
    """Sync router status.

    NAT-safe: agent-managed routers continuously report telemetry via the
    polling agent, so there is no direct connection to make from the cloud —
    return the latest agent-sourced status from the DB (with a freshness-derived
    online/offline). Non-agent (locally reachable) routers fall back to a direct
    RouterOS API sync.
    """
    from datetime import datetime as _dt
    service = RouterService(db, organization_id=_get_org_id(current_user))
    router = await service.get_by_id(router_id)
    if not router:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    if getattr(router, "agent_installed", False):
        online = False
        if router.last_poll_at:
            elapsed = (_dt.utcnow() - router.last_poll_at).total_seconds()
            online = elapsed < (router.agent_poll_interval or 30) * 3
        return RouterSyncResponse(
            success=True,
            message="Status updated from polling agent" if online else "Polling agent has not reported recently",
            router_id=router_id,
            status="online" if online else "offline",
            uptime=router.uptime,
            last_seen=router.last_seen,
            routeros_version=router.routeros_version,
            board_name=router.board_name,
            cpu_load=router.cpu_load,
            total_memory=router.total_memory,
            free_memory=router.free_memory,
        )

    # Non-agent router: attempt a direct API sync (works only on reachable nets)
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
    return RouterSyncResponse(
        success=False,
        message="Failed to sync router (no polling agent and direct API unreachable)",
        router_id=router_id,
    )


@router.get("/{router_id}/resources", response_model=Dict[str, Any])
async def get_router_resources(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return the router's system resources from stored agent telemetry.

    NAT-safe: serves the latest values reported by the polling agent (CPU,
    memory, uptime, version, board) plus board/arch captured at bootstrap —
    no direct RouterOS connection is attempted. This is what the device-detail
    page renders, so it no longer shows N/A for NAT'd routers.
    """
    from app.schemas.router import format_uptime_mikrotik

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    rtype = router_obj.router_type.value if router_obj.router_type else "mikrotik"
    return {
        "cpu_load": router_obj.cpu_load or 0,
        "free_memory": router_obj.free_memory or 0,
        "total_memory": router_obj.total_memory or 0,
        "free_hdd_space": router_obj.free_hdd_space or 0,
        "total_hdd_space": router_obj.total_hdd_space or 0,
        "uptime": format_uptime_mikrotik(router_obj.uptime) or "0s",
        "version": router_obj.routeros_version or "",
        "board_name": router_obj.board_name or "",
        "platform": "MikroTik" if rtype == "mikrotik" else rtype,
        "architecture_name": router_obj.architecture or "",
        "cpu_count": router_obj.cpu_count,
    }


@router.get("/{router_id}/action-script/{action}", response_class=PlainTextResponse)
async def get_router_action_script(
    router_id: int,
    action: str,
    token: str = Query(..., description="Provisioning/access token"),
    u: Optional[str] = Query(None, description="username (set_limits)"),
    lu: Optional[str] = Query(None, description="limit-uptime e.g. 1h (set_limits)"),
    lb: Optional[str] = Query(None, description="limit-bytes-total in bytes (set_limits)"),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Return a RouterOS .rsc for an agent-delivered router action.

    Fetched + imported by the polling agent (queued via fetch_import). Auth uses
    the access token embedded in the queued URL (the router has no user JWT).
    """
    from app.core.security import verify_token

    try:
        verify_token(token, token_type="access")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    service = RouterService(db)
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    if action == "sync_time":
        # Use the tenant's configured timezone (default Africa/Nairobi).
        tz = "Africa/Nairobi"
        if router_obj.organization_id:
            from app.models.organization import Organization
            res = await db.execute(
                select(Organization).where(Organization.id == router_obj.organization_id)
            )
            org = res.scalar_one_or_none()
            if org and org.timezone:
                tz = org.timezone
        return (
            "/system/ntp/client/set enabled=yes servers=time.google.com,time.cloudflare.com\n"
            f":do {{ /system/clock/set time-zone-name={tz} }} on-error={{}}\n"
            ":log info \"CVACTION: time synced\"\n"
        )

    if action == "reboot":
        # NAT-safe reboot: the agent imports this .rsc which schedules a reboot a
        # few seconds out so the import (and its result report) completes first.
        return (
            ":log info \"CVACTION: reboot requested by CodeVertex\"\n"
            ":delay 3s\n"
            "/system/reboot\n"
        )

    if action == "backup":
        # NAT-safe backup: run /system/backup/save locally on the router. The
        # file stays on the router (downloadable via winbox/ftp); the backend
        # records the request + timestamp in router_backups.
        return (
            ":local bname (\"codevertex-\" . [:pick [/system/clock/get date] 0 11])\n"
            ":do { /system/backup/save name=$bname } on-error={ :log warning \"CVACTION: backup failed\" }\n"
            ":log info \"CVACTION: backup saved\"\n"
        )

    if action == "set_limits":
        # Router-side hard caps on a hotspot user (queued right after create_user as
        # defense-in-depth, so the router self-enforces time/data even if the cloud
        # reconciler is down). u=username, lu=limit-uptime (e.g. "1h", blank=skip),
        # lb=limit-bytes-total in bytes (blank=skip).
        if not u:
            return ":log warning \"CVACTION: set_limits missing username\"\n"
        sets = []
        if lu:
            sets.append(f"limit-uptime={lu}")
        if lb:
            sets.append(f"limit-bytes-total={lb}")
        if not sets:
            return ":log info \"CVACTION: set_limits no-op (unlimited plan)\"\n"
        return (
            f":do {{ /ip/hotspot/user/set [find name=\"{u}\"] {' '.join(sets)} }} "
            f"on-error={{ :log warning \"CVACTION: set_limits failed\" }}\n"
            f":log info \"CVACTION: limits set for {u}\"\n"
        )

    if action == "set_api_password":
        # Sync the router's management/API user password to the backend's stored
        # copy after a rotation, so the backend's direct-API path keeps working.
        # The password is read from the DB here (NOT passed in the fetch URL), so
        # it is never logged in the agent's queued URL.
        uname = router_obj.username or "admin"
        pw = router_obj.password or ""
        if not pw:
            return ":log warning \"CVACTION: set_api_password no stored password\"\n"
        return (
            f":do {{ /user set [find name=\"{uname}\"] password=\"{pw}\" }} "
            f"on-error={{ :log warning \"CVACTION: set_api_password failed\" }}\n"
            ":log info \"CVACTION: API user password synced\"\n"
        )

    if action == "sync_hotspot":
        org_slug = ""
        if router_obj.organization_id:
            from app.models.organization import Organization
            res = await db.execute(select(Organization).where(Organization.id == router_obj.organization_id))
            org = res.scalar_one_or_none()
            org_slug = org.slug if org else ""
        base = (settings.backend_url or "").rstrip("/")
        return (
            f":do {{ /tool/fetch url=\"{base}/api/v1/provisioning/templates/login.html?org_slug={org_slug}\" dst-path=hotspot/login.html }} on-error={{}}\n"
            f":do {{ /tool/fetch url=\"{base}/api/v1/provisioning/templates/alogin.html?org_slug={org_slug}\" dst-path=hotspot/alogin.html }} on-error={{}}\n"
            ":do { /ip/hotspot/profile/set [find] html-directory=hotspot } on-error={}\n"
            ":log info \"CVACTION: hotspot files synced\"\n"
        )

    if action == "vpn":
        # Durable WireGuard enrollment for an already-bootstrapped (pre-WG) router.
        # Emits the SAME WG client config as the bootstrap so the router creates
        # the cvvpn interface, peers the server, gets a tunnel IP and POSTs its
        # public key to /bootstrap/wg-register -- no manual re-bootstrap needed.
        from app.services.wireguard import WireGuardService
        from app.core.security import create_access_token
        from datetime import timedelta as _td
        from urllib.parse import quote as _quote

        wg = WireGuardService(db)
        if not wg.enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WireGuard is not configured on the platform",
            )
        tunnel_ip = await wg.allocate_ip(router_obj)
        # Reserve the tunnel IP so the reconcile loop + register callback agree
        # (allocate_ip is idempotent, so re-fetching the script keeps the same IP).
        router_obj.vpn_address = tunnel_ip
        await db.commit()
        reg_token = create_access_token(
            {"sub": "0", "type": "access", "permissions": ["provisioning.execute"]},
            expires_delta=_td(hours=2),
        )
        base = (settings.backend_url or "").rstrip("/")
        wg_register_url = (
            f"{base}/api/v1/provisioning/bootstrap/wg-register"
            f"?token={reg_token}&identity={_quote(router_obj.name or '')}"
        )
        lines = wg.build_bootstrap_lines(tunnel_ip=tunnel_ip, wg_register_url=wg_register_url)
        return "\n".join(lines) + "\n"

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {action}")


@router.post("/{router_id}/enroll-vpn", response_model=Dict[str, Any])
async def enroll_router_vpn(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Enroll an already-bootstrapped router into the WireGuard overlay (NAT-safe).

    Queues an agent action-script that runs the WG client config on the router
    (create cvvpn, peer the server, allocate the tunnel IP, register the pubkey),
    so a router bootstrapped BEFORE WG existed joins the tunnel WITHOUT a manual
    re-bootstrap. The WG server reconcile loop then adds the peer + the per-router
    winbox DNAT (winbox reachable at vpn:<winbox_port>).
    """
    from app.services.wireguard import WireGuardService

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    wg = WireGuardService(db)
    if not wg.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WireGuard is not configured on the platform",
        )
    if not (getattr(router_obj, "agent_installed", False) and getattr(router_obj, "agent_token", None)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Router has no polling agent installed; re-bootstrap it first",
        )

    cmd_id = await _queue_agent_action(db, router_obj, "vpn", current_user.id)
    return {
        "message": "VPN enrollment queued; the router joins the tunnel on its next agent poll (~30s).",
        "command_id": cmd_id,
        "winbox_port": router_obj.winbox_port,
    }


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
    """Get active hotspot + PPPoE connections — NAT-safe (agent-sourced).

    Routers are behind NAT so the cloud cannot query them directly. The polling
    agent reports its active hotspot/PPPoE user list on each poll (stored on the
    router row); we serve that here. For non-agent (locally reachable) routers we
    fall back to a direct RouterOS query.

    Each entry: {user, type, address, mac-address, uptime}. Key names mirror the
    frontend's expectations (``user`` / ``mac-address``).
    """
    import json as _json

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # NAT-safe path: serve the agent-reported list.
    if getattr(router_obj, "agent_installed", False):
        raw = getattr(router_obj, "active_users_json", None)
        if not raw:
            return []
        try:
            users = _json.loads(raw)
        except (ValueError, TypeError):
            return []
        return [
            {
                "user": u.get("username", ""),
                "name": u.get("username", ""),
                "type": u.get("type", ""),
                "address": u.get("address", ""),
                "mac-address": u.get("mac", ""),
                "uptime": u.get("uptime", ""),
            }
            for u in users
            if isinstance(u, dict)
        ]

    # Non-agent router: attempt a direct RouterOS query (reachable nets only).
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        return []
    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port
    )
    if not connection:
        # NAT-safe contract: never raise a 502 here, just report no live data.
        return []
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
    """Disconnect a hotspot or PPPoE user — NAT-safe (queues an agent command).

    The agent body already supports the ``disconnect`` action (removes the active
    hotspot/PPPoE session locally). For non-agent routers we fall back to a direct
    RouterOS call.
    """
    from app.services.router_agent import RouterAgentService

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # NAT-safe path: queue a disconnect command the agent picks up on next poll.
    if getattr(router_obj, "agent_installed", False):
        agent_service = RouterAgentService(db)
        cmd = await agent_service.queue_command(
            router_id=router_id,
            action="disconnect",
            params={"username": username, "type": user_type},
            priority=2,
            source="manual",
        )
        await db.commit()
        return {
            "message": "Disconnect queued to the router agent (applies on next poll, ~30s)",
            "queued": True,
            "command_id": cmd.id,
            "username": username,
            "type": user_type,
        }

    # Non-agent router: direct RouterOS call.
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

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

    # NAT-safe path: deliver via the polling agent (no direct connection).
    if getattr(router_obj, "agent_installed", False):
        cmd_id = await _queue_agent_action(db, router_obj, "sync_time", current_user.id)
        return {
            "success": True,
            "queued": True,
            "command_id": cmd_id,
            "message": "Time sync queued to the router agent (applies on next poll, ~30s)",
            "ntp_servers": ["time.google.com", "time.cloudflare.com"],
        }

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

    # NAT-safe path: deliver via the polling agent (re-downloads templates +
    # points the hotspot profile at them) — no direct connection / FTP needed.
    if getattr(router_obj, "agent_installed", False):
        cmd_id = await _queue_agent_action(db, router_obj, "sync_hotspot", current_user.id)
        return {
            "success": True,
            "queued": True,
            "command_id": cmd_id,
            "message": "Hotspot file sync queued to the router agent (applies on next poll, ~30s)",
        }

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


@router.post("/{router_id}/test", response_model=Dict[str, Any])
async def test_router_connection(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Test router reachability — NAT-safe (agent liveness, no direct connect).

    A router behind NAT can never be reached by an outbound cloud connection, so
    "test connection" reports whether the polling agent has phoned home recently
    (within 3x the poll interval). Non-agent routers fall back to a direct probe.
    """
    from datetime import datetime as _dt

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    if getattr(router_obj, "agent_installed", False):
        interval = router_obj.agent_poll_interval or 30
        seconds_since = None
        online = False
        if router_obj.last_poll_at:
            seconds_since = int((_dt.utcnow() - router_obj.last_poll_at).total_seconds())
            online = seconds_since < interval * 3
        if online:
            return {
                "success": True,
                "online": True,
                "mode": "agent",
                "message": f"Polling agent is online (last poll {seconds_since}s ago)",
                "last_poll_at": router_obj.last_poll_at.isoformat() if router_obj.last_poll_at else None,
                "seconds_since_last_poll": seconds_since,
            }
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Polling agent has not reported recently"
                + (f" (last poll {seconds_since}s ago)" if seconds_since is not None else " (never polled)")
            ),
        )

    # Non-agent router: direct reachability probe (reachable nets only).
    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No credentials available for router")
    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port,
    )
    if not connection:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    await client.disconnect(connection)
    return {"success": True, "online": True, "mode": "direct", "message": "Router connection successful"}


@router.post("/{router_id}/reboot", response_model=Dict[str, Any])
async def reboot_router(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Reboot the router — NAT-safe (queues an agent action-script).

    The agent downloads + imports the ``reboot`` action-script (which delays a
    few seconds, then runs ``/system/reboot``). Non-agent routers reboot via a
    direct RouterOS command.
    """
    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    if getattr(router_obj, "agent_installed", False):
        cmd_id = await _queue_agent_action(db, router_obj, "reboot", current_user.id)
        return {
            "success": True,
            "queued": True,
            "command_id": cmd_id,
            "message": "Reboot queued to the router agent (applies on next poll, ~30s)",
        }

    from app.integrations.mikrotik import get_mikrotik_client
    from app.services.router_provisioning import get_router_credentials

    credentials = await get_router_credentials(db, router_id)
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No credentials available for router")
    client = get_mikrotik_client()
    connection = await client.connect(
        ip_address=router_obj.ip_address,
        username=credentials["username"],
        password=credentials["password"],
        port=router_obj.port,
    )
    if not connection:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to router")
    try:
        await client.execute_command(connection, "/system/reboot", method="call")
        return {"success": True, "message": "Router reboot initiated"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to reboot: {str(e)}")
    finally:
        await client.disconnect(connection)


@router.get("/{router_id}/events", response_model=List[Dict[str, Any]])
async def get_router_events(
    router_id: int,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Device events timeline — merges RouterLog + RouterCommand history.

    NAT-safe: built purely from stored data (operation logs + the agent command
    queue), no direct router connection. Returns a unified, newest-first list.
    """
    from app.models.router import RouterLog as RouterLogModel
    from app.models.router_command import RouterCommand

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    events: List[Dict[str, Any]] = []

    # Operation logs
    log_res = await db.execute(
        select(RouterLogModel)
        .where(RouterLogModel.router_id == router_id)
        .order_by(RouterLogModel.created_at.desc())
        .limit(limit)
    )
    for log in log_res.scalars().all():
        events.append({
            "id": f"log-{log.id}",
            "kind": "log",
            "action": log.action,
            "details": log.details or log.error_message or "",
            "success": log.success,
            "status": "success" if log.success else "failed",
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    # Agent command history
    cmd_res = await db.execute(
        select(RouterCommand)
        .where(RouterCommand.router_id == router_id)
        .order_by(RouterCommand.created_at.desc())
        .limit(limit)
    )
    for cmd in cmd_res.scalars().all():
        events.append({
            "id": f"cmd-{cmd.id}",
            "kind": "command",
            "action": cmd.action,
            "details": cmd.result_message or (cmd.source or ""),
            "success": cmd.status == "success",
            "status": cmd.status,
            "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
        })

    # Merge newest-first
    events.sort(key=lambda e: e["created_at"] or "", reverse=True)
    return events[:limit]


@router.get("/{router_id}/payments", response_model=List[Dict[str, Any]])
async def get_router_payments(
    router_id: int,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Payments for subscriptions on this router (NAT-safe, DB-only).

    Joins subscriptions.router_id -> invoices -> payments, newest-first.
    """
    from app.models.subscription import Subscription
    from app.models.billing import Invoice, Payment
    from app.models.user import User as UserModel

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    res = await db.execute(
        select(Payment, Invoice, Subscription, UserModel)
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .join(Subscription, Invoice.subscription_id == Subscription.id)
        .outerjoin(UserModel, Payment.user_id == UserModel.id)
        .where(Subscription.router_id == router_id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )

    payments: List[Dict[str, Any]] = []
    for payment, invoice, subscription, user in res.all():
        customer = None
        if user:
            customer = getattr(user, "full_name", None) or getattr(user, "username", None) or getattr(user, "email", None)
        payments.append({
            "id": payment.id,
            "payment_number": payment.payment_number,
            "amount": float(payment.amount) if payment.amount is not None else 0,
            "currency": payment.currency,
            "payment_method": payment.payment_method.value if payment.payment_method else None,
            "status": payment.status.value if payment.status else None,
            "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
            "invoice_number": invoice.invoice_number,
            "subscription_id": subscription.id,
            "subscription_username": subscription.username,
            "customer": customer,
        })
    return payments


@router.get("/{router_id}/backups", response_model=List[Dict[str, Any]])
async def list_router_backups(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List backup history for a router (NAT-safe, DB-only)."""
    from app.models.router import RouterBackup

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    res = await db.execute(
        select(RouterBackup)
        .where(RouterBackup.router_id == router_id)
        .order_by(RouterBackup.created_at.desc())
    )
    return [
        {
            "id": b.id,
            "name": b.name,
            "status": b.status,
            "backup_type": b.backup_type,
            "size_bytes": b.size_bytes,
            "message": b.message,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        }
        for b in res.scalars().all()
    ]


@router.post("/{router_id}/backup", response_model=Dict[str, Any])
async def create_router_backup(
    router_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Create a router backup — NAT-safe (queues an agent action-script).

    Queues the ``backup`` action-script (runs ``/system/backup/save`` locally on
    the router) and records a RouterBackup history row tied to the queued command
    so its status reconciles when the agent reports back. Returns JSON (the
    frontend now renders history rather than downloading a blob).
    """
    from app.models.router import RouterBackup

    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    if not getattr(router_obj, "agent_installed", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Backups require the polling agent (router is behind NAT and not directly reachable)",
        )

    cmd_id = await _queue_agent_action(db, router_obj, "backup", current_user.id)

    backup = RouterBackup(
        router_id=router_id,
        name=f"codevertex-{datetime.utcnow().strftime('%Y-%m-%d-%H%M')}",
        status="pending",
        backup_type="binary",
        command_id=cmd_id,
        requested_by=current_user.id,
    )
    db.add(backup)
    await db.commit()
    await db.refresh(backup)

    return {
        "success": True,
        "queued": True,
        "command_id": cmd_id,
        "backup_id": backup.id,
        "name": backup.name,
        "status": backup.status,
        "message": "Backup queued to the router agent (runs /system/backup/save on next poll, ~30s)",
    }


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

    # Ensure a real VPN-mapped winbox port. Legacy/seeded routers may still be
    # on the local 8291 (no VPN port); assign one from the VPN range so the
    # remote winbox URL becomes valid once the router is provisioned onto the VPN.
    if not RouterService._is_vpn_winbox_port(router_obj.winbox_port):
        try:
            new_port = await service._assign_winbox_port()
            router_obj.winbox_port = new_port
            await db.commit()
            await db.refresh(router_obj)
        except Exception:
            await db.rollback()

    # Ensure the router is enrolled on the VPN WITH the management firewall rule
    # (winbox 8291 + API 8728 allowed from the tunnel), so remote winbox works
    # without a manual router edit. NAT-safe + idempotent: queues the agent 'vpn'
    # action-script (build_bootstrap_lines). Best-effort.
    try:
        from app.services.wireguard import WireGuardService

        if (
            WireGuardService(db).enabled
            and getattr(router_obj, "agent_installed", False)
            and getattr(router_obj, "agent_token", None)
        ):
            await _queue_agent_action(db, router_obj, "vpn", current_user.id)
    except Exception:
        pass

    # Generate new secure password
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    new_password = ''.join(secrets.choice(alphabet) for _ in range(16))

    # Update router password in database
    await service.update_router(router_id, {"password": new_password})

    # Push the new password to the router's API user so the backend's direct-API
    # path stays in sync with the DB (NAT-safe via the agent; the set_api_password
    # action-script reads the new password from the DB, not from the URL/logs).
    try:
        if getattr(router_obj, "agent_installed", False) and getattr(router_obj, "agent_token", None):
            await _queue_agent_action(db, router_obj, "set_api_password", current_user.id)
    except Exception:
        pass

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
    service = RouterService(db, organization_id=_get_org_id(current_user))
    router_obj = await service.get_by_id(router_id)
    if not router_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Router not found")

    # Single source of truth (service): a remote URL is returned ONLY when the
    # router has a real VPN-mapped port + configured domain — otherwise None and
    # we present the honest LOCAL URL (no fake vpn.* host that resolves nowhere).
    remote_winbox_url = await service.get_winbox_url(router_id)
    vpn_domain = await service.resolve_vpn_domain(router_obj)
    local_winbox_url = f"{router_obj.ip_address}:8291"

    return {
        "router_id": router_id,
        "router_name": router_obj.name,
        "winbox_port": router_obj.winbox_port,
        "winbox_url": remote_winbox_url or local_winbox_url,
        "local_winbox_url": local_winbox_url,
        "vpn_domain": vpn_domain,
        "is_configured": remote_winbox_url is not None,
        "tooltip": "Click to copy. Ensure port 8291 is open on the device. After copying, paste this to the Winbox connect field."
    }