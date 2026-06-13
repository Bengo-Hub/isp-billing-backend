# ISP Billing — Connectivity & Billing Audit + Remediation (2026‑06‑13)

> This is the **accurate, evidence-based** audit. The older `backend-audit.md`
> (scored 95/100, "production‑ready") was an optimistic AI doc and does **not**
> reflect the breaks documented here. Trust this one.

## 0. How the system is actually wired (prod)

- **Cloud backend**: `ispbillingapi.codevertexitsolutions.com` (k3s ns `isp-billing`, 2 pods). Frontend: `ispbilling.codevertexitsolutions.com`.
- **Routers are behind NAT**, so the cloud backend **cannot** open a connection
  to a router's API (`192.168.x:8728`). Two outbound, NAT‑safe mechanisms exist:
  1. **Bootstrap** (`/api/v1/provisioning/bootstrap/*`): user pastes a `/tool fetch … /import`
     one‑liner; the router enables API/FTP/winbox, creates the `codevertex-api`
     user, POSTs a scan report + `notify` callback. **Works.**
  2. **Script‑based provisioning** (`GET /api/v1/provisioning/provision-script/{session}`):
     router fetches + runs the full hotspot/PPPoE/bridge/DNS/NAT config locally,
     then POSTs `/complete`. **Works behind NAT.**
  3. **Polling agent** (`/api/v1/router-agent/*`): a `/system/scheduler` on the
     router polls `/poll-text` every ~30 s and runs `create_user/disable_user/…`.
     This is what turns a *paid subscription* into actual router access.
- **No VPN / RADIUS** is deployed in this cluster (the `vpn.centipidbilling.com`
  / RADIUS `10.8.0.1` references in the snapshots belong to the original Centipid
  reference deployment and **do not exist here**). → see §3 WireGuard.

Live DB state at audit time (org 3 = "Demo ISP" / `demo-isp`):
- 1 router `MikroTik1` (ip `192.168.100.7`), `agent_installed=t` but **last poll 2026‑03‑11**.
- `router_commands` = **0 rows ever**. 2 ACTIVE subs, **`is_router_synced=false`** (never synced).
- Gateways: only **Paystack** (platform‑level). No M‑PESA / cash gateway configured.
- Plan id 21 "1HR TEST PACKAGE" (KES 1, 1 day). Admin login: `demo` / `demo123` (ISP_ADMIN, org 3).

## 1. Confirmed bugs (and fixes shipped on branch `fix/router-connectivity-and-billing`)

| # | Severity | Bug | Evidence | Fix |
|---|----------|-----|----------|-----|
| 1 | 🔴 | **Polling agent never installed.** `bootstrap.py` set `agent_installed=true` but nothing fetched/imported the agent installer. DB: 0 commands ever, no poll since Mar. | `api/v1/provisioning/bootstrap.py` (no agent fetch); DB `router_commands`=0 | Bootstrap now fetches + imports the agent installer (`bootstrap.py` install block). |
| 2 | 🔴 | **Agent "installer" never created a scheduler.** `get_agent_script` returned only the polling *body* → `/import` ran one poll, no recurrence. | `api/v1/router_agent.py::get_agent_script` returned body only | Split into `installer` (default; downloads body + creates `/system/scheduler`) and `body` modes. New `_generate_agent_installer_script`. |
| 3 | 🔴 | **Cash/manual payment never activated the subscription.** Only Paystack/M‑PESA called `_activate_subscription_on_payment`. `verify_payment` marked invoice PAID but stopped there. | `modules/billing/payments.py::verify_payment`; `business/billing.py POST /payments`→`create_payment` (PENDING only) | Activation hooked into shared `_apply_payment_to_invoice`; manual `verify_payment` activates on full payment; offline `create_payment` (cash/bank) now auto‑completes + reconciles. |
| 4 | 🟠 | **Agent `create_user` ignored `rate_limit` and assumed the `plan_<id>` profile existed.** No bandwidth shaping; add could fail. | `api/v1/router_agent.py` create_user block (urate parsed, never used) | create_user now ensures the hotspot/PPP profile exists with `rate-limit=$urate` before adding the user. `_calculate_rate_limit` returns "" (unlimited) instead of `0/0`. |
| 5 | 🟡 | **Dead/duplicate code.** 3 unused private command‑gen methods in `provisioning/service.py`; dead static `/provisioning/bootstrap/complete` endpoint (hardcoded 192.168.88.1). | `service.py:835‑967`; `bootstrap.py get_complete_script` (unreferenced) | Removed (134 + 88 lines). |

### Still‑open / folded into VPN work
- 🟠 **Provisioning path selection.** `POST /provisioning/workflow` (Step‑3) always uses **direct RouterOS API** to `router.ip_address`, which fails for a NATed router. Fix: once the WireGuard tunnel exists, `router.ip_address` becomes the tunnel IP (reachable); also add a reachability check that falls back to the script‑based path. (§4)
- ℹ️ Stale ACTIVE subscriptions whose `end_date` passed are not flipped to EXPIRED unless the Celery expiry beat runs — verify beat schedule includes the expiry sweep.

## 2. What works and should NOT be touched
- Bootstrap one‑liner + scan‑report + notify callbacks.
- Script‑based provisioning (`provision-script` + `/complete`).
- Command queue + agent poll/report protocol (`router_agent.py` service + endpoints).
- `_activate_subscription_on_payment` (correct; was just never called by the cash path).

## 3. Our own WireGuard VPN (replaces the non‑existent centipid VPN)

Goal: routers dial an **outbound** WireGuard tunnel to *our* server; the backend
then reaches each router over the tunnel (direct API + remote winbox), and the
agent stays as a NAT fallback.

**Topology**
- WG server in cluster (ns `vpn`), wg0 = `10.8.0.1/16`, listen UDP `51820`,
  exposed on the node `77.237.232.66` (hostPort/NodePort) at DNS `vpn.codevertexitsolutions.com`.
- Each router: tunnel IP `10.8.0.<n>/16`, peer = server pubkey, endpoint =
  `vpn.codevertexitsolutions.com:51820`, `persistent-keepalive=25s`.
- Backend manages router at `10.8.0.<n>:8728`; remote winbox via `10.8.0.<n>:8291`.

**Backend pieces (code)**
- DB: `router.vpn_address`, `vpn_public_key`, `vpn_private_key_enc`, `vpn_enabled`.
- `WireGuardService`: generate keypair, allocate next free `10.8.0.x`, register peer, build the router's WG client RSC.
- Bootstrap: add `/interface/wireguard` + peer + tunnel `/ip/address`; then set `router.ip_address = vpn_address` so subsequent API/provisioning uses the tunnel.
- Reconcile: WG server pulls the authoritative peer list from a backend endpoint (`GET /router-agent/wg-peers`, server‑token auth) and applies `wg syncconf` (avoids in‑cluster `kubectl exec`).

**External prerequisites (USER action — cannot self‑serve):**
1. **DNS**: create `vpn.codevertexitsolutions.com` A → `77.237.232.66` (DNS is managed at the registrar; see `iot-domain-dns-missing`).
2. **UDP exposure**: open/forward UDP `51820` to the node and allow the WG pod `NET_ADMIN` + `/dev/net/tun` (privileged); enable `net.ipv4.ip_forward` (already on for k8s).
3. Confirm Calico `natOutgoing` so backend‑pod → `10.8.0.0/16` is SNAT'd to the node (return path works).

## 4. Deploy (GitOps)
- Backend image: CI in `Bengo-Hub/isp-billing-backend` builds `docker.io/codevertex/isp-billing-backend:<sha>`; bump `tag` in `devops-k8s/apps/isp-billing-backend/values.yaml`; ArgoCD app `isp-billing-backend` auto‑syncs. Migrations run idempotently on container start.
- WG server: new `devops-k8s/apps/vpn` + ArgoCD app.

## 5. Live e2e plan (dry‑run gated — every router command shown for approval first)
1. Bootstrap the live router (RB951Ui‑2HnD, RouterOS 7.18.2) → API user + agent scheduler + (WG tunnel).
2. Provision hotspot (script path) → bridge/DHCP/DNS/hotspot/walled‑garden.
3. As `demo`, buy "1HR TEST PACKAGE" for a test customer (creates PENDING sub + invoice).
4. Reconcile as **cash** (`POST /billing/payments` method=cash, or record‑manual + verify) → invoice PAID → sub ACTIVE → `create_user` queued → agent creates the hotspot user with rate‑limit.
5. Connect a device, log into the hotspot with the issued credentials, confirm internet.
6. **Cleanup**: delete all test rows (subscription, invoice, payment, router_commands, hotspot user on router) per the E2E cleanup rule.

**Lockout safety**: provisioning never adds the WAN to the bridge and keeps winbox/8291 reachable; we dry‑run each command.
