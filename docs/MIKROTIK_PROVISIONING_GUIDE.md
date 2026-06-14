# MikroTik Router Provisioning — Technical Guide

> **Accuracy note (2026-06):** This guide describes the system as it is actually
> implemented today: a **NAT-safe, agent-polling** model with an **external
> captive portal**. There is **no RADIUS, no User Manager, and no direct
> cloud→router API requirement** in production. Earlier revisions of this doc
> described a RADIUS / direct-API / queue-tree design that the code never shipped;
> that content has been removed. The authoritative connectivity audit is
> [`AUDIT-AND-REMEDIATION-2026-06.md`](./AUDIT-AND-REMEDIATION-2026-06.md).

## Table of Contents
1. [The core constraint: routers are behind NAT](#1-the-core-constraint-routers-are-behind-nat)
2. [The three NAT-safe channels](#2-the-three-nat-safe-channels)
3. [End-to-end provisioning workflow](#3-end-to-end-provisioning-workflow)
4. [Step 1 — Bootstrap (one-liner)](#4-step-1--bootstrap-one-liner)
5. [Step 2 — Device scan](#5-step-2--device-scan)
6. [Step 3 — Service provisioning (the generated .rsc)](#6-step-3--service-provisioning-the-generated-rsc)
7. [The polling agent](#7-the-polling-agent)
8. [Captive-portal flow](#8-captive-portal-flow)
9. [Subscriber lifecycle (create / disable / enable)](#9-subscriber-lifecycle-create--disable--enable)
10. [Payments → activation](#10-payments--activation)
11. [Network defaults & RouterOS v6/v7](#11-network-defaults--routeros-v6v7)
12. [Tenant timezone](#12-tenant-timezone)
13. [Reprovisioning & clean-slate idempotency](#13-reprovisioning--clean-slate-idempotency)
14. [Captive-portal troubleshooting](#14-captive-portal-troubleshooting)
15. [General troubleshooting](#15-general-troubleshooting)
16. [Code map](#16-code-map)

---

## 1. The core constraint: routers are behind NAT

In production the cloud backend (`ispbillingapi.codevertexitsolutions.com`) **cannot
open a connection to a router's API** (`192.168.x.x:8728`) because the router sits
behind NAT on a customer LAN. Every integration is therefore **router-initiated
(outbound)**: the router fetches scripts and polls the backend; the backend never
dials the router.

A direct RouterOS API path still exists in the code (`MikroTikClient`) and is used
**only** as a fallback for routers the backend *can* reach (same LAN, or once a
WireGuard tunnel exists — see the audit doc §3). It is never the primary path.

```
                 (outbound HTTPS only)
   ┌──────────┐   fetch script / poll    ┌─────────────────────┐
   │ MikroTik │ ───────────────────────► │   Cloud Backend     │
   │  (NAT)   │ ◄─────────────────────── │   (FastAPI)         │
   └──────────┘   commands in response   └─────────────────────┘
        ▲  the backend cannot initiate a connection inbound
```

---

## 2. The three NAT-safe channels

| # | Channel | Endpoint(s) | Purpose |
|---|---------|-------------|---------|
| 1 | **Bootstrap** | `GET /provisioning/bootstrap/command` → `/bootstrap/script` → `/bootstrap/scan-report` + `/bootstrap/notify` | First touch: enable API/FTP/Winbox, create the `codevertex-api` user, scan the device, **install the polling agent**, (optionally enroll WireGuard). |
| 2 | **Script-based provisioning** | `GET /provisioning/provision-script/{session_id}` → `/provision-script/{session_id}/complete` | Step 3 service setup. The router fetches a full `.rsc` (bridge / pool / DHCP / DNS / NAT / hotspot / walled-garden / captive portal) and runs it locally, then POSTs completion. |
| 3 | **Polling agent** | `POST /router-agent/poll-text`, `POST /router-agent/report` | Ongoing command channel. A `/system/scheduler` on the router polls every ~30 s and runs queued commands (`create_user`, `disable_user`, `enable_user`, `disconnect`, `fetch_import`, …). This is what turns a *paid subscription* into actual router access. |

Authentication differs per channel:
- Bootstrap / provision-script use a short-lived **provisioning JWT** (1-hour) in the URL.
- The agent uses a per-router **`X-Router-Token`** (random 64-hex, hashed at rest), generated during bootstrap.

---

## 3. End-to-end provisioning workflow

The frontend wizard has 3 steps; behind them is the create-only session + the
NAT-safe channels above.

```
Step 1  Connection  → POST /provisioning/sessions (create-only) returns session_id
                      GET  /provisioning/bootstrap/command?...&session_id=...
                      User pastes the one-liner in the router terminal.
                      Router: identity + API/FTP/Winbox + codevertex-api user
                              + POST scan-report + POST notify (+ install agent).

Step 2  Device scan → scan data arrives via /bootstrap/scan-report (router→cloud).
                      UI shows interfaces; WAN auto-detected (default route iface),
                      WAN auto-excluded from the bridge port list.

Step 3  Services    → POST /provisioning/workflow (or the script path).
                      For a NAT'd router the UI uses GET /provision-script/{id}:
                      router fetches the generated .rsc and runs it, then POSTs
                      /provision-script/{id}/complete → session COMPLETED.
```

> `POST /provisioning/workflow` both creates a session and runs the background
> workflow over the **direct** RouterOS API; for a NAT'd router that direct path
> fails, so the UI uses the **script-based** path (`provision-script`) instead.
> `POST /provisioning/sessions` is the *create-only* variant (no provisioning
> started) used to obtain a `session_id` to thread through the bootstrap callback.

---

## 4. Step 1 — Bootstrap (one-liner)

`GET /api/v1/provisioning/bootstrap/command` returns a copy-paste command:

```routeros
/tool fetch mode=https url="https://<backend>/api/v1/provisioning/bootstrap/script?token=<JWT>&identity=<NAME>&api_port=8728&interface=ether1" dst-path=codevertex.rsc;:delay 2s;/import codevertex.rsc; :delay 1s; /tool fetch mode=https url="https://<backend>/api/v1/provisioning/bootstrap/notify?session_id=<SID>&token=<JWT>&identity=<NAME>&status=bootstrap_completed" http-method=post;
```

The downloaded `codevertex.rsc` (`bootstrap.py::get_bootstrap_script`) does, in order:

1. Set system identity.
2. Enable **API** (port from query), **FTP** (21), **Winbox**, and move **SSH** to **2222**.
3. Create user group `codevertex-api` and user (`mikrotik_api_username` from settings)
   in group `codevertex-api` — comment `"Codevertex ISP Billing API - DO NOT DELETE"`.
4. Verify the WAN interface exists; tune memory logging.
5. **POST a scan report** (`/bootstrap/scan-report`) with interfaces, version, board,
   WAN interface (derived from the default route), service counts, IPs, DNS.
6. Download the captive-portal templates (`login.html`, `alogin.html`) to `hotspot/`
   when the user's org slug is known.
7. **Install the polling agent**: fetch `/router-agent/script/{router_id}?token=<agent>`
   (the *installer*) and `/import` it — this registers the recurring scheduler.
8. Optionally emit a **WireGuard** client config + register callback (only if the
   platform has WG configured; otherwise it prints `[SKIP]`).

The outer one-liner then POSTs `/bootstrap/notify`, which marks the session
`bootstrap_completed`, stores encrypted API credentials on the router row, and
broadcasts completion over WebSocket so the UI auto-advances. `notify` correlates
by `session_id` first, then falls back to router IP / identity.

> The agent token is **reused** if the router already has one; it is **not**
> regenerated on every bootstrap-command preview (regenerating would 401 the agent
> already running on the device).

---

## 5. Step 2 — Device scan

There is no inbound scan. The bootstrap script POSTs the scan to
`/bootstrap/scan-report`, which `store_scanned_config()` persists on the router so
the UI's device-scan view can render cached data. The scan determines:

- the interface list shown for bridge-port selection, and
- the **WAN interface** (the interface of the `0.0.0.0/0` default route), which is
  **auto-excluded** from bridge ports to prevent management lockout.

---

## 6. Step 3 — Service provisioning (the generated .rsc)

`GET /provisioning/provision-script/{session_id}` (`workflow.py`) builds a single
`.rsc` from `generate_configuration_commands` + `generate_hotspot_commands` /
`generate_pppoe_commands` (`app/modules/provisioning/commands.py`). Each command is
wrapped in `:do {…} on-error={…}`; critical steps abort, non-critical ones warn and
continue. At the end the script POSTs `/provision-script/{session_id}/complete`.

**Order of operations (hotspot path):**

1. **Identity, NTP, timezone** (timezone from the org; default `Africa/Nairobi`).
2. **Clean slate** — remove the previous run's `codevertex-*` objects first (see §13).
3. **Bridge** `codevertex-bridge` (ensured, not stripped from the default bridge).
4. **Bridge ports** — each selected port is removed from any current bridge, then
   added to `codevertex-bridge`. **WAN is filtered out** (`filter_wan_from_bridge_ports`).
5. **Gateway IP** on the bridge, **IP pool** `codevertex-pool`, **DNS** (`allow-remote-requests`).
6. **DHCP server** `codevertex-dhcp` + network — DHCP hands clients the **router/gateway
   as their DNS** (so captive-portal detection works), not 8.8.8.8.
7. **NAT masquerade** out the WAN interface (`comment=codevertex-masquerade`).
8. Hotspot: enable FTP, create CA + server **certificate** (for RFC 7710/8910 /
   DHCP Option 114), hotspot **profile** `codevertex-hsprof`
   (`login-by=http-chap,http-pap,https,mac-cookie`), assign the SSL cert.
9. Create the **hotspot server** — **named `ISP-Hotspot`** (from service-config
   enrichment), bound to `codevertex-bridge`, `addresses-per-mac=1`, `idle-timeout=5m`.
10. **Captive-portal redirect install** — fetch `login.html` + `alogin.html` from the
    backend into `hotspot/` and set `html-directory=hotspot` on the profile (see §8 — this
    is what makes the redirect actually happen).
11. Gateway **ip-binding bypass**, **walled garden** (portal + payment hosts),
    **captive-portal-detection DNS static** entries, **DNS-redirect NAT** (force
    :53 through the router), **DoH block** (reject :443 to known DoH IPs), optional
    **anti-sharing** TTL rules.

> **Hotspot server name caveat:** the server is `ISP-Hotspot`, the *profile* is
> `codevertex-hsprof`. Cleanup/reset must match the **server by interface**
> (`interface=codevertex-bridge`), not by `name~"codevertex"`. See
> [`reset-router-provision.md`](./reset-router-provision.md).

---

## 7. The polling agent

Installed during bootstrap (channel 3). Two script modes from
`GET /router-agent/script/{router_id}` (`router_agent.py`):

- **`installer`** (default): removes any prior `codevertex-agent` scheduler + cached
  `cvagent.rsc`, downloads the agent **body** to `cvagent.rsc`, creates a
  `/system/scheduler name="codevertex-agent" interval=<poll>s on-event="/import file-name=cvagent.rsc"`,
  and runs it once immediately. **This is what makes polling recurring** — a
  previous bug returned only the body, so `/import` ran a single poll and never
  scheduled anything.
- **`body`**: the actual loop — collect telemetry (CPU/mem/uptime/version + active
  hotspot/PPP users), `POST /router-agent/poll-text`, parse the **pipe-delimited**
  command lines, execute them, and `POST /router-agent/report` with results.

Backend side (`app/services/router_agent.py`):
- `queue_command()` enqueues a `RouterCommand` (priority, source, expiry).
- `handle_poll()` updates telemetry (DB + Redis 5-min TTL), stores the agent-reported
  **active users** (the only NAT-safe source for the "Active Users" tab), returns up
  to N pending commands and marks them `sent`.
- `handle_report()` flips commands to `success`/`failed` (with retry/backoff);
  `subscription_sync` results update `is_router_synced`.
- Plain-text `/poll-text` avoids needing a JSON parser on RouterOS v6.

Command wire format (one per line): `action|param1|...|command_id`, e.g.
`create_user|jane|pass|hotspot|plan_7|10M/5M|<cmd-id>`.

---

## 8. Captive-portal flow

This is an **external** captive portal: unauthenticated clients are redirected to
the ISP-billing **frontend** buy page, not MikroTik's built-in login form.

```
Client → AP → bridged ether port → hotspot DHCP lease (172.31.x.x, gateway=router DNS)
   │  opens any HTTP page (unauthenticated)
   ▼
MikroTik hotspot intercepts → serves hotspot/login.html
   │  login.html <meta refresh> → {frontend}/buy/{org_slug}?mac=..&ip=..
   ▼  (walled garden allows the portal + payment hosts)
Frontend buy page → redeem voucher OR buy package (M-PESA / Paystack)
   │  backend creates the hotspot user NAT-safely (agent queues create_user)
   ▼
Client authenticates (returning users: POST /hotspot/{org}/login) → internet
```

Key pieces:
- **`login.html`** (`templates.py::generate_login_template`, served from
  `GET /provisioning/templates/login.html?org_slug=…`) meta-refreshes to
  `{frontend_url}/buy/{org_slug}` and also has a fallback username/password form that
  POSTs to MikroTik's `$(link-login-only)`.
- **`alogin.html`** is the post-auth page; it redirects to the org's configured
  `hotspot_redirect_url`.
- **`html-directory=hotspot`** on the hotspot profile is what activates these custom
  pages. **Without it the router serves its built-in login form and no external
  redirect happens** (this was the "lease but no popup" bug — now fixed in
  `generate_hotspot_commands`, which fetches both templates and sets the directory).
- **Captive-portal detection** DNS static entries resolve OS probe domains
  (`connectivitycheck.gstatic.com`, `captive.apple.com`, `www.msftconnecttest.com`, …)
  to the gateway with short TTL so the device shows the "Sign in to Wi-Fi" popup.
  DNS-redirect NAT + DoH blocking stop clients bypassing this with hardcoded/encrypted DNS.

> Templates reach the router two ways, both router-initiated: (a) the **bootstrap**
> script downloads them up-front, and (b) **provisioning** re-fetches them and sets
> `html-directory=hotspot`. (b) is the load-bearing one for the redirect.

---

## 9. Subscriber lifecycle (create / disable / enable)

User changes never dial the router; they are **queued** for the agent:

- **Create** — `_sync_hotspot_user_to_router()` (`app/api/v1/portal/hotspot.py`) is the
  single source of truth, shared by voucher redeem, returning-user login, and
  post-payment. It prefers the agent (`queue_command("create_user", …)` with the
  plan's `rate_limit` and `profile=plan_<id>`); the agent **ensures the profile exists
  with the right `rate-limit`** before adding the user. Direct API is fallback only.
- **Disable / disconnect on expiry** — queued `disable_user` / `disconnect` commands
  (subscription expiry sweep → `subscription_sync`).
- **Enable on renewal** — queued `enable_user`.

Vouchers (`app/api/v1/business/vouchers.py`): `POST /business/vouchers/generate`
creates a batch (shared `batch_id`), each with **auto-generated hotspot credentials**
and an optional pre-use **expiry** (shelf life). Limits are **not** stored on the
voucher — they are derived from the linked plan at redeem time.

---

## 10. Payments → activation

`BillingService.create_payment(is_manual=…)` (`app/modules/billing/service.py`):

- **Offline** methods (`cash`, `bank_transfer`) and any `is_manual=true`
  reconciliation are recorded **COMPLETED** immediately and applied to the invoice.
- **Online** (M-PESA / card) stay **PENDING** until the gateway callback confirms.
- `_apply_payment_to_invoice()` is the shared path: when the invoice becomes fully
  paid **and** is linked to a subscription, it activates that subscription and marks
  it for router sync — identical behaviour across M-PESA, Paystack and manual/cash
  (previously only the gateway webhooks activated; cash did not).

For hotspot self-service purchases (`/hotspot/{org}/purchase` →
`_process_successful_payment`), a voucher with hotspot credentials is generated and
the hotspot user is queued onto the router via the shared helper. **All gateways are
platform-level** (`organization_id IS NULL`); ISPs don't configure their own.

---

## 11. Network defaults & RouterOS v6/v7

- Default subnet **`172.31.0.0/16`** (gateway `.0.1`, pool `.0.2`–`.255.254`).
  `calculate_network_config()` also handles /22, /23, /24.
- Bridge `codevertex-bridge`; pool `codevertex-pool`; DHCP `codevertex-dhcp`;
  hotspot profile `codevertex-hsprof`; hotspot **server `ISP-Hotspot`**.
- Version handling: `is_v7_or_later()` branches NTP and timezone syntax (v7 uses
  `servers=` and IANA `time-zone-name=`; v6 uses `primary-ntp/secondary-ntp` and
  `time-zone-autodetect`). The generated `.rsc` uses slash-separated paths
  (`/ip/firewall/nat/add …`) which both versions accept. See
  [`mikrotikv6-v7-comparison.md`](./mikrotikv6-v7-comparison.md).
- **No DROP-all firewall rule** is added (avoids lockout); only permissive
  management-allow rules (`comment=codevertex-allow-*`) — and those are **never**
  removed by cleanup.

---

## 12. Tenant timezone

Each organization has a `timezone` (default **`Africa/Nairobi`**, EAT UTC+3). It is
injected into the provision script (clock set at provision time) and can be re-applied
later via the router `sync_time` action. v6 routers fall back to timezone auto-detect.

---

## 13. Reprovisioning & clean-slate idempotency

`generate_configuration_commands()` emits a **clean-slate block first** so a
reprovision (e.g. to add `ether2`) starts from a known state and re-adds never hit
"already exists". Every removal is `on-error`-guarded and scoped to `codevertex-*`
objects, in dependency order (dependents → deps):

- hotspot **server by `interface=codevertex-bridge`** (name varies — `ISP-Hotspot`),
  hotspot profile `codevertex-hsprof`, gateway ip-binding, walled-garden hosts/IPs,
- DHCP server + network, IP pool,
- captive-detection DNS static, DNS-redirect NAT, masquerade NAT, DoH-block filter,
  anti-sharing mangle/filter,
- bridge IP, then the bridge itself.

What is deliberately **never** touched: the default `bridge`, the WAN interface, the
management IP, and the `codevertex-allow-*` management firewall rules.

For a manual wipe before re-provisioning, use
[`reset-router-provision.md`](./reset-router-provision.md) (which matches the same
"remove hotspot by interface" rule and also stops the polling-agent scheduler).

---

## 14. Captive-portal troubleshooting

**Symptom: client gets a `172.31.x.x` lease but no portal popup / no redirect.**
- **Most common cause:** `html-directory` was not set / `login.html` was not
  installed, so the hotspot serves MikroTik's **built-in** username/password form and
  never meta-refreshes to the buy page. **Fixed in provisioning** —
  `generate_hotspot_commands` now `/tool fetch`es `login.html` + `alogin.html` into
  `hotspot/` and sets `html-directory=hotspot`. Verify on the router:
  `/ip/hotspot/profile/print` shows `html-directory: hotspot`, and the files exist
  under `/file/print` as `hotspot/login.html` and `hotspot/alogin.html`.
- If templates are missing, re-run provisioning (preferred) or re-fetch them:
  `/tool fetch url="https://<backend>/api/v1/provisioning/templates/login.html?org_slug=<slug>" dst-path=hotspot/login.html` (and `alogin.html`).
- Confirm the client got the **router as its DNS** (DHCP hands gateway as DNS); if a
  device uses hardcoded `8.8.8.8`/DoH the detection probe may slip through — the
  DNS-redirect NAT and DoH-block rules exist to prevent this.
- Confirm the buy host is in the **walled garden** (otherwise the redirect target is
  itself blocked pre-auth).

**Symptom: the router's own built-in open Wi-Fi says "No internet" yet still browses.**
- The provision script installs **global** `/ip/dns/static` captive-detection entries
  (probe domains → gateway) and a **global** masquerade. These also affect clients on
  the router's **built-in Wi-Fi**, which is **not** part of `codevertex-bridge` and so
  is **not** gated by the hotspot. Such clients reach the internet (via masquerade)
  but their OS captive probe resolves to the gateway and gets intercepted, so the OS
  shows "No internet / sign-in required" even though browsing works.
- **The built-in open Wi-Fi bypasses the hotspot entirely** — anyone on it gets
  unauthenticated internet. For production, the built-in Wi-Fi should be **disabled**
  or **bridged into `codevertex-bridge`** so it is gated by the hotspot like the wired
  ports. (Provisioning intentionally does not touch the default bridge / built-in
  Wi-Fi to avoid locking out the operator, so this is a manual step.)

**Symptom: after authenticating, sites won't load for ~a while.**
- Captive-detection DNS static entries use a short **TTL (5m)** precisely so the
  client's cache clears soon after auth. If you raised the TTL, post-auth clients can
  keep resolving probe/real domains to the gateway for up to the TTL.

**Symptom: voucher redeemed / payment succeeded but the client still can't log in.**
- The hotspot user is created **asynchronously** via the agent. Check the agent is
  online (`GET /router-agent/status/{router_id}`, `is_online=true`) and that a
  `create_user` command went `pending → sent → success`
  (`GET /router-agent/commands/{router_id}`). If the agent never polls, nothing is
  created — see §15.

---

## 15. General troubleshooting

- **"device mode not allowed"** when importing: run
  `/system/device-mode/update mode=advanced` (newer RouterOS restricts fetch/scheduler).
- **Bootstrap fetch fails / 308 redirect:** RouterOS `/tool fetch` doesn't follow
  redirects and the `mode=` must match the URL scheme. The backend forces `https`
  when `force_https` or `x-forwarded-proto: https` is set; ensure the backend base
  URL is `https://`.
- **Agent never polls (no commands ever delivered):** confirm the bootstrap actually
  imported the agent installer (`router_obj` existed at bootstrap so a token was
  issued) and that the `codevertex-agent` scheduler exists
  (`/system/scheduler/print`). Historically `agent_installed=true` was set without
  anything installing the agent — both that and the "installer returned body only"
  bug are fixed.
- **`create_user` fails / no bandwidth shaping:** the agent ensures the
  hotspot/PPP profile exists with `rate-limit=<plan>` before adding the user; an
  empty rate limit means "unlimited" (not `0/0`).
- **Bridge removal fails with "interface in use":** the hotspot server is still bound
  to the bridge — remove it **by interface** first (see §13 and the reset script).
- **Stale `sent` commands:** `reset_stale_sent_commands()` returns commands stuck in
  `sent` (e.g. router rebooted mid-poll) back to `pending`.

---

## 16. Code map

| Concern | File |
|---------|------|
| Bootstrap command + script + scan-report + notify + wg-register | `app/api/v1/provisioning/bootstrap.py` |
| Provision-script (Step 3) + workflow + sessions | `app/api/v1/provisioning/workflow.py` |
| Command generation (config / hotspot / pppoe, clean-slate, WAN filter) | `app/modules/provisioning/commands.py` |
| Captive-portal templates (`login.html` / `alogin.html`) | `app/api/v1/provisioning/templates.py` |
| Polling agent: command queue, poll/report, token | `app/services/router_agent.py` |
| Polling agent: endpoints + RSC installer/body generators | `app/api/v1/router_agent.py` |
| Hotspot portal (redeem / login / purchase) + NAT-safe user sync | `app/api/v1/portal/hotspot.py` |
| Voucher admin (generate batch + credentials + expiry) | `app/api/v1/business/vouchers.py` |
| Payments → invoice → subscription activation | `app/modules/billing/service.py` |
| Direct RouterOS API client (fallback only) | `app/integrations/mikrotik.py` |
| RouterOS v6 vs v7 syntax reference | `docs/mikrotikv6-v7-comparison.md` |
| Manual reset before reprovisioning | `docs/reset-router-provision.md` |
| Authoritative connectivity/billing audit | `docs/AUDIT-AND-REMEDIATION-2026-06.md` |

---

**Last updated:** 2026-06 · Reflects the NAT polling-agent + external captive-portal
implementation. Supersedes the earlier RADIUS/direct-API revision.
