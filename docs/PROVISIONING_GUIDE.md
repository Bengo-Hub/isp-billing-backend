# MikroTik Provisioning — Overview (Codevertex ISP Billing)

> **Canonical reference:** the full technical detail lives in
> [`MIKROTIK_PROVISIONING_GUIDE.md`](./MIKROTIK_PROVISIONING_GUIDE.md). This file
> is a short conceptual overview of how a MikroTik router performs the ISP-billing
> functions (captive portal, access control, expiry, usage). It was previously
> written around a RADIUS / direct-API / queue-tree design that the code never
> shipped; it has been corrected to the actual **NAT polling-agent + external
> captive-portal** implementation.

## How the system is actually wired

Routers are behind NAT, so the cloud backend **cannot** connect to a router's API.
Everything is router-initiated over three outbound channels:

1. **Bootstrap** — user pastes a `/tool fetch … /import` one-liner; the router
   enables API/FTP/Winbox, creates the `codevertex-api` user, POSTs a scan report +
   notify, and **installs the polling agent**.
2. **Script-based provisioning** — the router fetches a generated `.rsc`
   (`GET /provisioning/provision-script/{session_id}`) that builds the bridge, pool,
   DHCP, DNS, NAT, hotspot, walled-garden and **captive-portal redirect**, then POSTs
   `/complete`.
3. **Polling agent** — a `/system/scheduler` polls `/router-agent/poll-text` every
   ~30 s and runs queued commands (`create_user`, `disable_user`, `enable_user`,
   `disconnect`, `fetch_import`). This is what turns a paid subscription into router
   access.

There is **no RADIUS and no User Manager** in this system. Authentication is local
(hotspot users / PPP secrets) created via the agent; the captive portal is **external**
(the ISP-billing frontend buy page), not MikroTik's built-in login form.

## 1. Captive-portal (hotspot) flow

```
Client → AP → bridged ether port → hotspot DHCP lease (172.31.x.x; DNS = router)
   │ opens any HTTP page while unauthenticated
   ▼
MikroTik hotspot intercepts → serves hotspot/login.html
   │ login.html <meta refresh> → {frontend}/buy/{org_slug}?mac=..&ip=..
   ▼ (walled garden allows the portal + payment hosts)
Frontend buy page → redeem voucher OR buy package (M-PESA / Paystack)
   │ backend queues create_user for the polling agent (NAT-safe)
   ▼
Client authenticated → internet
```

The redirect only works because provisioning installs `hotspot/login.html` +
`hotspot/alogin.html` and sets **`html-directory=hotspot`** on the hotspot profile.
Without that the router shows its built-in login form and never redirects (see the
captive-portal troubleshooting section in the canonical guide).

Walled garden allows unauthenticated access to: the org's portal/buy host, the API
host, and payment hosts (`*.paystack.com`, `*.safaricom.co.ke`, …). Captive-portal
**detection** is handled by `/ip/dns/static` entries (OS probe domains → gateway,
short TTL), DNS-redirect NAT (force :53 through the router) and a DoH block.

## 2. Access-control mechanism

| Component | RouterOS path | Purpose |
|-----------|---------------|---------|
| Hotspot users | `/ip/hotspot/user` | Credentials + per-user limits |
| User profiles | `/ip/hotspot/user/profile` | Bandwidth (`rate-limit`), session rules |
| Active sessions | `/ip/hotspot/active` | Connected users (read by the agent) |
| Walled garden | `/ip/hotspot/walled-garden` | Hosts reachable before auth |
| IP bindings | `/ip/hotspot/ip-binding` | Bypass/MAC reservations |
| PPPoE | `/ppp/secret`, `/ppp/profile`, `/ppp/active` | PPPoE creds, profiles, sessions |

When a client connects: DHCP assigns a `172.31.x.x` lease → unauthenticated → HTTP
intercepted and redirected to the buy page → after redeem/purchase the agent creates
the hotspot user (ensuring the `plan_<id>` profile exists with the right `rate-limit`)
→ client authenticates → profile rate limit applies → session tracked in
`/ip/hotspot/active`.

## 3. Package subscription models

- **Self-service (portal):** buy/redeem on the captive portal → on payment success a
  voucher + hotspot credentials are generated and the user is queued onto the router
  via the agent. All gateways are platform-level (`organization_id IS NULL`).
- **Admin-created:** admin creates a subscription/voucher; the agent provisions the
  user on the router; the customer logs in via the captive portal
  (`POST /hotspot/{org}/login` for returning users).

## 4. Expiry & disconnection

The subscription expiry sweep queues `disable_user` / `disconnect` commands (source
`subscription_sync`) for the agent rather than connecting to the router directly. On
renewal an `enable_user` command is queued. There is no direct cloud→router call.

## 5. Bandwidth management

Per-plan `rate-limit` on the hotspot/PPP **user profile** (e.g. `10M/5M`). The agent
creates/updates the profile from the plan's download/upload speeds when it creates the
user. (Queue trees / PCQ are not part of the shipped provisioning.)

## 6. Usage tracking

The polling agent reports the live active-user list (username, type, address, MAC,
uptime) on each poll; `handle_poll()` stores it on the router row (the only NAT-safe
source for the dashboard "Active Users" tab) and pushes telemetry to Redis (5-min TTL).

## Live streaming (provisioning UI)

The provisioning UI streams progress over **WebSocket** (`/provisioning/ws/{session_id}`):
each step/command emits a log line (info/success/warning/error) and progress updates;
completion is broadcast when the router POSTs the provision-script / bootstrap-notify
callback. See `app/api/v1/provisioning/stream.py` and `live_streaming.py`.

---

For bootstrap details, the generated `.rsc` order of operations, the polling-agent
protocol, RouterOS v6/v7 handling, reprovisioning clean-slate, and full
troubleshooting (including the captive-portal "lease but no popup" symptom), see
[`MIKROTIK_PROVISIONING_GUIDE.md`](./MIKROTIK_PROVISIONING_GUIDE.md).

**Last updated:** 2026-06 · Corrected to the NAT polling-agent + external
captive-portal implementation.
