"""WireGuard VPN overlay control-plane endpoints.

These endpoints are consumed by the in-cluster WireGuard server's reconcile
loop (NOT by user-facing clients). Authentication is via a shared bearer token
(``settings.wg_peer_sync_token``) carried in the ``Authorization: Bearer <tok>``
header — the same token is mounted into the WG server pod via the
``wg-server-keys`` Secret. This avoids granting the backend kube-exec rights:
the WG server pulls the authoritative peer list and applies it locally.

Security:
- The peer list contains only PUBLIC keys + tunnel IPs + winbox ports. No
  private key material is ever exposed.
- The endpoint 503s when no sync token is configured (VPN disabled), and 401s
  on a missing/incorrect token. Constant-time comparison avoids token oracles.
"""

import hmac
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.services.wireguard import WireGuardService

logger = get_logger(__name__)

router = APIRouter()


class WGPeer(BaseModel):
    router_id: int
    public_key: str
    allowed_ips: str           # "10.8.0.<n>/32"
    tunnel_ip: str             # "10.8.0.<n>"
    winbox_port: Optional[int] = None


class WGPeersResponse(BaseModel):
    server_address: str        # the WG server's own tunnel IP (10.8.0.1)
    subnet: str                # "10.8.0.0/16"
    peers: List[WGPeer]


def _require_sync_token(authorization: Optional[str]) -> None:
    """Authenticate the WG server reconcile loop via the shared bearer token."""
    expected = (settings.wg_peer_sync_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VPN peer sync is not configured (WG_PEER_SYNC_TOKEN unset)",
        )
    provided = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid VPN peer sync token",
        )


@router.get("/peers", response_model=WGPeersResponse)
async def list_vpn_peers(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> WGPeersResponse:
    """Authoritative WireGuard peer list for the server reconcile loop.

    Returns every VPN-enabled router's public key + tunnel IP + winbox port so
    the WG server can ``wg syncconf`` peers and set up the per-router winbox
    DNAT (vpn:<winbox_port> -> <tunnel_ip>:8291).
    """
    _require_sync_token(authorization)

    svc = WireGuardService(db)
    peers = await svc.list_peers()
    return WGPeersResponse(
        server_address=svc.server_address,
        subnet=svc.subnet,
        peers=[WGPeer(**p) for p in peers],
    )
