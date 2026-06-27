"""WireGuard VPN overlay service.

Manages the per-router WireGuard tunnel that lets the cloud backend reach a
NAT'd MikroTik router over an outbound tunnel (direct API + remote winbox).

Security model (important):
- The WG **server** keypair lives ONLY in the k8s Secret ``wg-server-keys``.
  The server PUBLIC key reaches the backend via ``settings.wg_server_public_key``
  and is handed to routers during bootstrap.
- Each **router** generates and keeps its OWN private key (RouterOS v7
  auto-generates it on ``/interface/wireguard/add``). The private key is NEVER
  transmitted to or stored by the backend — only the router's PUBLIC key is
  POSTed back to the ``wg-register`` callback and stored on the router row.
- The WG server reconcile loop pulls the authoritative peer list from the
  backend (``GET /api/v1/vpn/peers``) and applies it with ``wg``/``iptables`` —
  the backend never needs kube-exec rights.

This service therefore generates NOTHING private server-side. It only:
- allocates the next free tunnel IP (``10.8.0.<n>``),
- records a router's reported public key (``register_peer``),
- builds the RouterOS WireGuard bootstrap lines, and
- exposes server pubkey / endpoint / subnet from settings.
"""

import ipaddress
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.router import Router

logger = get_logger(__name__)

# RouterOS interface + peer naming. Guarded by :if find=… checks so re-running
# the bootstrap is idempotent (never creates a duplicate interface/peer).
WG_INTERFACE_NAME = "cvvpn"
WG_PEER_COMMENT = "codevertex-vpn-server"


class WireGuardService:
    """Backend-side WireGuard overlay management (no private key material)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Server / endpoint info (from settings) ──

    @property
    def enabled(self) -> bool:
        return settings.wg_enabled

    @property
    def server_public_key(self) -> str:
        return settings.wg_server_public_key.strip()

    @property
    def endpoint(self) -> str:
        return settings.wg_endpoint.strip()

    @property
    def endpoint_host(self) -> str:
        return self.endpoint.rsplit(":", 1)[0] if ":" in self.endpoint else self.endpoint

    @property
    def endpoint_port(self) -> int:
        if ":" in self.endpoint:
            try:
                return int(self.endpoint.rsplit(":", 1)[1])
            except ValueError:
                pass
        return 51820

    @property
    def subnet(self) -> str:
        return settings.wg_subnet.strip()

    def _network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_network(self.subnet, strict=False)

    @property
    def _prefix_len(self) -> int:
        return self._network().prefixlen

    @property
    def server_address(self) -> str:
        """The WG server's tunnel IP (first host in the subnet, e.g. 10.8.0.1)."""
        net = self._network()
        return str(net.network_address + 1)

    # ── Tunnel IP allocation ──

    async def _used_addresses(self) -> set:
        """All tunnel IPs currently assigned to routers (+ the server's)."""
        result = await self.db.execute(
            select(Router.vpn_address).where(Router.vpn_address.isnot(None))
        )
        used = {row[0] for row in result.fetchall() if row[0]}
        used.add(self.server_address)
        return used

    async def allocate_ip(self, router: Optional[Router] = None) -> str:
        """Allocate the next free tunnel IP (10.8.0.<n>) in the subnet.

        Idempotent for a given router: if the router already has a vpn_address
        it is returned unchanged (re-running bootstrap must not churn the IP).
        """
        if router is not None and router.vpn_address:
            return router.vpn_address

        net = self._network()
        used = await self._used_addresses()

        # Skip the network address and the server address (.1); start at .2.
        for host in net.hosts():
            candidate = str(host)
            if candidate == self.server_address:
                continue
            if candidate not in used:
                logger.info(f"Allocated WG tunnel IP {candidate}")
                return candidate

        raise RuntimeError(
            f"No free WireGuard tunnel IP available in {self.subnet}"
        )

    # ── Peer registration (router reports its OWN public key) ──

    async def register_peer(
        self, router: Router, public_key: str
    ) -> Router:
        """Persist a router's reported WG public key and mark the tunnel enabled.

        Stores ONLY the public key (no private material). Ensures the router has
        an allocated tunnel IP.

        IMPORTANT: enrollment does NOT repoint management (``ip_address``) onto the
        tunnel. The router reporting its pubkey only means the router-side config
        ran — it does NOT mean the WireGuard handshake completed (RouterOS < v7 has
        no WG, the upstream may block UDP 51820, etc.). Cutting ``ip_address`` over
        to the tunnel IP on mere enrollment is what broke remote management: direct
        API / WinBox then targeted a tunnel that never came up. Management therefore
        stays on its existing address here; promotion to the tunnel IP must be gated
        on a CONFIRMED handshake (see ``promote_router_to_tunnel`` / the future
        reconcile handshake-report). The tunnel IP lives in ``vpn_address``.
        """
        public_key = (public_key or "").strip()
        if not public_key:
            raise ValueError("Empty WireGuard public key")

        if not router.vpn_address:
            router.vpn_address = await self.allocate_ip(router)

        router.vpn_public_key = public_key
        router.vpn_enabled = True
        # NOTE: do NOT set router.ip_address = router.vpn_address here (premature
        # cutover onto an unconfirmed tunnel — see docstring).

        await self.db.flush()
        logger.info(
            f"Registered WG peer for router {router.id}: "
            f"address={router.vpn_address} pubkey={public_key[:12]}…"
        )
        return router

    # ── Authoritative peer list (consumed by the WG server reconcile loop) ──

    async def list_peers(self) -> List[dict]:
        """Return the authoritative peer list for the WG server reconcile loop.

        Each entry:
            {
              "public_key": "<router pubkey>",
              "allowed_ips": "10.8.0.<n>/32",
              "winbox_port": <int|null>,   # for the DNAT rule
              "tunnel_ip": "10.8.0.<n>",
              "router_id": <int>,
            }
        """
        result = await self.db.execute(
            select(Router).where(
                Router.vpn_enabled.is_(True),
                Router.vpn_public_key.isnot(None),
                Router.vpn_address.isnot(None),
            )
        )
        peers = []
        for r in result.scalars().all():
            peers.append(
                {
                    "router_id": r.id,
                    "public_key": r.vpn_public_key,
                    "allowed_ips": f"{r.vpn_address}/32",
                    "tunnel_ip": r.vpn_address,
                    "winbox_port": r.winbox_port,
                }
            )
        return peers

    # ── RouterOS bootstrap lines ──

    def build_bootstrap_lines(
        self,
        tunnel_ip: str,
        wg_register_url: str,
    ) -> List[str]:
        """Build the RouterOS WireGuard client config lines for the bootstrap.

        Idempotent: every create is guarded by a ``find`` length check so a
        re-run never duplicates the interface, peer, or address. RouterOS v7
        auto-generates the interface private key; we read back the PUBLIC key
        and POST it to ``wg_register_url`` so the backend can add us as a peer.

        ``tunnel_ip`` is the bare address (e.g. ``10.8.0.7``); the prefix is
        derived from the configured subnet so the router's wg interface address
        matches the server's /16.
        """
        net = self._network()
        prefix = net.prefixlen
        server_pub = self.server_public_key
        host = self.endpoint_host
        port = self.endpoint_port
        # Pin the peer endpoint to the RESOLVED server IP so the router does NOT depend on
        # its own DNS to reach the WG gateway. A NAT'd router whose endpoint-address DNS
        # name fails to resolve at peer-add time has NO endpoint and therefore never sends
        # a handshake (the observed "0 handshakes / no WG packets reach the node"). We
        # resolve server-side (the node IP is stable) and fall back to the DNS name.
        import socket
        try:
            endpoint_addr = socket.gethostbyname(host)
        except Exception:
            endpoint_addr = host
        allowed = f"{net.network_address}/{prefix}"  # e.g. 10.8.0.0/16
        iface = WG_INTERFACE_NAME

        # wg_register_url already carries ?token=…&identity=… ; the script
        # appends the pubkey as http-data so the JWT stays out of the (logged)
        # URL where possible.
        return [
            "",
            "# ── CodeVertex WireGuard VPN overlay (NAT-safe router management) ──",
            ":put \"Configuring CodeVertex VPN tunnel...\"",
            ":do {",
            f"  :if ([:len [/interface/wireguard/find name={iface}]] = 0) do={{",
            f"    /interface/wireguard/add name={iface} comment=\"CodeVertex VPN - DO NOT DELETE\"",
            f"    :put \"[OK] WireGuard interface {iface} created\"",
            "  } else={",
            f"    :put \"[SKIP] WireGuard interface {iface} already exists\"",
            "  }",
            "} on-error={ :put \"[FAIL] Could not create WireGuard interface\"; :log error \"VPN: wg interface add failed\" }",
            "",
            "# Add the CodeVertex server as a peer (idempotent on public-key)",
            ":do {",
            f"  :if ([:len [/interface/wireguard/peers/find public-key=\"{server_pub}\"]] = 0) do={{",
            f"    /interface/wireguard/peers/add interface={iface} \\",
            f"      public-key=\"{server_pub}\" \\",
            f"      endpoint-address={endpoint_addr} endpoint-port={port} \\",
            f"      allowed-address={allowed} persistent-keepalive=25s \\",
            f"      comment=\"{WG_PEER_COMMENT}\"",
            "    :put \"[OK] VPN server peer added\"",
            "  } else={",
            "    :put \"[SKIP] VPN server peer already exists\"",
            "  }",
            "} on-error={ :put \"[FAIL] Could not add VPN server peer\"; :log error \"VPN: wg peer add failed\" }",
            "",
            "# Assign the tunnel IP on the wg interface (idempotent)",
            ":do {",
            f"  :if ([:len [/ip/address/find address=\"{tunnel_ip}/{prefix}\" interface={iface}]] = 0) do={{",
            f"    /ip/address/add address={tunnel_ip}/{prefix} interface={iface} comment=\"CodeVertex VPN\"",
            f"    :put \"[OK] Tunnel IP {tunnel_ip}/{prefix} assigned\"",
            "  } else={",
            "    :put \"[SKIP] Tunnel IP already assigned\"",
            "  }",
            "} on-error={ :put \"[FAIL] Could not assign tunnel IP\"; :log error \"VPN: tunnel address add failed\" }",
            "",
            "# Allow CodeVertex VPN management (winbox 8291 + API 8728) FROM the tunnel",
            "# subnet only, placed at the top of the input chain so the router's default",
            "# drop does not block remote winbox over the tunnel. Idempotent on comment.",
            ":do {",
            f"  :if ([:len [/ip/firewall/filter/find comment=\"codevertex-vpn-mgmt\"]] = 0) do={{",
            f"    /ip/firewall/filter/add chain=input action=accept protocol=tcp \\",
            f"      dst-port=8291,8728 src-address={allowed} comment=\"codevertex-vpn-mgmt\"",
            f"    :do {{ /ip/firewall/filter/move [find comment=\"codevertex-vpn-mgmt\"] destination=0 }} on-error={{}}",
            "    :put \"[OK] VPN management firewall rule added (winbox/API from tunnel)\"",
            "  } else={",
            "    :put \"[SKIP] VPN management firewall rule already exists\"",
            "  }",
            "} on-error={ :put \"[WARN] Could not add VPN management firewall rule\"; :log warning \"VPN: mgmt firewall add failed\" }",
            "",
            "# Read back our OWN public key and register it with the backend.",
            "# (The PRIVATE key never leaves the router.)",
            ":do {",
            f"  :local wgPub [/interface/wireguard/get [find name={iface}] public-key]",
            "  :delay 1s",
            f"  /tool/fetch mode=https url=\"{wg_register_url}\" http-method=post \\",
            "    http-data=(\"public_key=\" . $wgPub) dst-path=wg-register.result",
            "  :put \"[OK] Registered VPN public key with CodeVertex\"",
            "  :log info \"VPN: registered wg public key\"",
            "} on-error={ :put \"[WARN] Failed to register VPN public key (will retry on next bootstrap)\"; :log warning \"VPN: wg-register failed\" }",
            "",
        ]
