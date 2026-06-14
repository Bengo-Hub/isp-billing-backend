# ISP Billing System - Backend Implementation Plan

**Document Version:** 2.1
**Last Updated:** 2026-02-01
**Project Status:** 88% Complete
**Target:** 100% Production-Ready Multi-Tenant ISP Billing Platform

---

> **⚠️ Status-correction note (2026-06):** Several sprints below are now stale.
> In particular, **Multi-Tenancy (Phase 4 / Sprints 9–10) is implemented**, not
> "PENDING" — the system has `Organization`/`OrganizationSettings`, tenant
> middleware/context, and `organization_id`-scoped queries throughout. The
> **Captive Portal (Sprint 12)** redirect is also implemented: provisioning
> installs `hotspot/login.html` + `alogin.html` (org-branded, served from
> `/provisioning/templates/*`) and sets `html-directory=hotspot`. **Paystack
> (Sprint 13)** is implemented (platform-level gateway). Note also that the
> router channel is the **NAT polling agent**, not RADIUS — the
> "User Manager / RADIUS" research bullets are background, not the shipped design.
> The authoritative, current view of how prod is wired is
> [`AUDIT-AND-REMEDIATION-2026-06.md`](./AUDIT-AND-REMEDIATION-2026-06.md); for
> provisioning see [`MIKROTIK_PROVISIONING_GUIDE.md`](./MIKROTIK_PROVISIONING_GUIDE.md).

---

## Executive Summary

This plan outlines the comprehensive backend implementation for a production-ready, multi-tenant ISP billing platform. Based on extensive research of industry leaders (Centipid, Splynx, WISPGate, Powerlynx), MikroTik integration patterns, and enterprise multi-tenancy best practices, this document tracks all features, their implementation status, and pending work required for production readiness.

---

## Research Findings Summary

### Industry Analysis (Competitors)
- **Centipid**: MikroTik-focused, hotspot/PPPoE, M-PESA integration, 3-step provisioning
- **Splynx**: Full ISP management, RADIUS, multi-vendor support, extensive reporting
- **WISPGate**: Cloud-based, multi-tenant, captive portal customization
- **Powerlynx**: Self-service portals, automated billing, voucher management

### MikroTik Integration Points
- **RouterOS API**: TCP ports 8728 (plain) / 8729 (SSL)
- **User Manager**: RADIUS server for authentication
- **Hotspot**: MAC-based auth, vouchers, walled garden
- **PPPoE**: Profile-based bandwidth, queue management

### Multi-Tenancy Patterns (from ERP-API Analysis)
- **Recommended**: Pool model with row-level security (TenantID on all tables)
- **Tenant Context**: Middleware-based with X-Tenant-Id header
- **Data Isolation**: Foreign key chaining (Business → Branch → Entity)
- **Configuration**: Per-tenant settings for payments, branding, notifications

---

## Current Architecture Status

### Technology Stack
| Component | Version | Status |
|-----------|---------|--------|
| FastAPI | 0.115.x | Implemented |
| PostgreSQL | 15+ | Implemented |
| SQLAlchemy | 2.0.36 | Implemented |
| Redis | 5.2.x | Implemented |
| Celery | 5.4.x | Implemented |
| Pydantic | 2.10.x | Implemented |
| Tenacity (Retry) | 9.0.x | Implemented |
| PyBreaker (Circuit) | 1.2.x | Implemented |

### Module Structure (Implemented)
- `app/modules/auth/` - Authentication, users, RBAC
- `app/modules/billing/` - Billing, payments, M-PESA
- `app/modules/routers/` - MikroTik management
- `app/modules/licences/` - Licence management
- `app/modules/provisioning/` - Device provisioning
- `app/modules/subscriptions/` - Subscription lifecycle
- `app/modules/plans/` - Service plans, templates
- `app/modules/notifications/` - Multi-channel notifications
- `app/modules/analytics/` - Reports, advanced analytics
- `app/modules/support/` - Ticket system
- `app/modules/gateways/` - Gateway management
- `app/modules/system/` - Configuration, initialization

---

## Sprint Breakdown

### Phase 1: Foundation (COMPLETED)

#### Sprint 1: Project Setup & Core Models
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| FastAPI project structure | COMPLETED | Modular architecture |
| PostgreSQL + Redis setup | COMPLETED | Docker Compose ready |
| SQLAlchemy 2.0 models | COMPLETED | 40+ tables |
| Alembic migrations | COMPLETED | Version controlled |
| JWT authentication | COMPLETED | Access + Refresh tokens |
| Environment configuration | COMPLETED | Pydantic Settings |

#### Sprint 2: MikroTik Router Integration
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| RouterOS API integration | COMPLETED | routeros-api package |
| Router CRUD endpoints | COMPLETED | Full management |
| PPPoE user handlers | COMPLETED | Profile management |
| Hotspot user handlers | COMPLETED | Voucher support |
| Hotspot login endpoint | COMPLETED | Two-strategy auth (voucher → subscription), MikroTik sync |
| Voucher management CRUD | COMPLETED | Admin generate/list/update/delete via /business/vouchers |
| Usage data fetching | COMPLETED | Real-time metrics |
| Connection monitoring | COMPLETED | CPU, memory, uptime |

#### Sprint 3: Device Provisioning System
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| 3-step provisioning workflow | COMPLETED | Connection → Config → Service |
| Live progress monitoring | COMPLETED | WebSocket streaming |
| Bootstrap command generation | COMPLETED | Token-based auth |
| Device connection verification | COMPLETED | Ping + API checks |
| Template-based configuration | COMPLETED | Versioned configs |
| Automatic rollback | COMPLETED | Error recovery |

---

### Phase 2: Billing & Payments (COMPLETED)

#### Sprint 4: Billing Engine
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| Invoice generation | COMPLETED | Automated + manual |
| Recurring billing cycles | COMPLETED | Celery scheduled |
| Usage-based billing | COMPLETED | Data tracking |
| Service lockout | COMPLETED | Non-payment handling |
| Payment reconciliation | COMPLETED | Auto-matching |

#### Sprint 5: M-PESA Integration
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| Daraja STK Push | COMPLETED | Customer-initiated |
| C2B callbacks | COMPLETED | Webhook handlers |
| Payment verification | COMPLETED | Transaction validation |
| Auto-activation | COMPLETED | Service enablement |
| Transaction logging | COMPLETED | Audit trail |

---

### Phase 3: Advanced Features (PARTIALLY COMPLETED)

#### Sprint 6: Licence Management
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| Subscription tracking | COMPLETED | Expiry monitoring |
| Payment logs | COMPLETED | Transaction history |
| Earnings dashboard | COMPLETED | Daily/weekly/monthly |
| Renewal notifications | COMPLETED | Automated alerts |
| Usage analytics | COMPLETED | Feature tracking |

#### Sprint 7: Package Management
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| Package templates | COMPLETED | Quick setup |
| Package categories | COMPLETED | Hotspot/PPPoE/Data |
| Bulk operations | COMPLETED | Mass updates |
| Device assignment | COMPLETED | Router-specific |
| FUP support | COMPLETED | Fair Usage Policy |

#### Sprint 8: Notification System
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| SMS integration | COMPLETED | Africa's Talking, Twilio |
| Email integration | COMPLETED | SMTP, SendGrid, AWS SES |
| Template system | COMPLETED | Variable substitution |
| User type differentiation | COMPLETED | Hotspot vs PPPoE |
| Notification history | COMPLETED | Delivery tracking |

---

### Phase 4: Multi-Tenancy (PENDING - CRITICAL)

#### Sprint 9: Tenant Foundation
**Status:** PENDING
**Priority:** CRITICAL
**Estimated Duration:** 2 weeks

| Task | Status | Notes |
|------|--------|-------|
| Tenant/Organization model | PENDING | Core multi-tenant entity |
| Tenant middleware | PENDING | X-Tenant-Id header handling |
| Row-level security | PENDING | tenant_id on all tables |
| Tenant context management | PENDING | contextvars for request isolation |
| Tenant-aware queries | PENDING | Automatic filtering |
| Tenant isolation tests | PENDING | Data security verification |

**Implementation Details:**
- Add `tenant_id` foreign key to all business entities
- Create TenantMiddleware to extract and validate tenant from JWT/header
- Use Python contextvars for request-scoped tenant context
- Implement query filters using SQLAlchemy events

#### Sprint 10: Tenant Configuration
**Status:** PENDING
**Priority:** CRITICAL
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Per-tenant settings | PENDING | Configuration isolation |
| Tenant payment gateways | PENDING | M-PESA, Paystack per tenant |
| Tenant notification settings | PENDING | SMS/Email providers |
| Tenant limits | PENDING | Max users, routers, data |
| Tenant feature flags | PENDING | Module enablement |

---

### Phase 5: Branding & Customization (PENDING)

#### Sprint 11: Tenant Branding
**Status:** PENDING
**Priority:** HIGH
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Branding settings model | PENDING | Colors, logos, fonts |
| Logo/asset storage | PENDING | S3/local file handling |
| Theme configuration | PENDING | Primary/secondary colors |
| Email template branding | PENDING | Tenant-specific templates |
| SMS signature branding | PENDING | Custom sender names |

**Fields Required (from ERP-API pattern):**
- primary_color, secondary_color
- logo_url, favicon_url
- company_name, tagline
- footer_text, support_email
- css_custom_overrides

#### Sprint 12: Captive Portal Customization
**Status:** PARTIAL
**Priority:** HIGH
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Hotspot portal login API | COMPLETED | POST /{org_slug}/login with voucher + subscription auth |
| MikroTik user sync on login | COMPLETED | Auto-creates/updates hotspot user with plan limits |
| Hotspot portal config/packages/purchase | COMPLETED | Full purchase flow with M-PESA/Paystack |
| PPPoE portal login/purchase | COMPLETED | Full PPPoE customer portal |
| Captive portal templates | PENDING | Customizable HTML/CSS |
| Portal asset management | PENDING | Images, backgrounds |
| Welcome message config | PENDING | Custom messaging |
| Terms & conditions | PENDING | Tenant-specific T&C |
| Redirect URL config | PENDING | Post-auth destination |
| Portal preview API | PENDING | Admin preview feature |

---

### Phase 6: Payment Integration Enhancement (PENDING)

#### Sprint 13: Paystack Integration
**Status:** PENDING
**Priority:** MEDIUM
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Paystack API client | PENDING | HTTP client with circuit breaker |
| Card payment flow | PENDING | Initialize → Verify |
| Bank transfer support | PENDING | Transfer receipts |
| Webhook handlers | PENDING | Event processing |
| Payment reconciliation | PENDING | Auto-matching |

#### Sprint 14: Advanced Payment Features
**Status:** PENDING
**Priority:** MEDIUM
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Payment gateway abstraction | PENDING | Provider-agnostic interface |
| Automatic refunds | PENDING | Reversal handling |
| Partial payments | PENDING | Installment support |
| Payment reminders | PENDING | Automated dunning |
| Payment analytics | PENDING | Success rates, trends |

---

### Phase 7: Performance & Scalability (PENDING)

#### Sprint 15: Caching Strategy
**Status:** PENDING
**Priority:** HIGH
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Redis caching layer | PENDING | Hot data caching |
| Query result caching | PENDING | Expensive queries |
| Session caching | PENDING | User sessions |
| Rate limit data | PENDING | Request counters |
| Cache invalidation | PENDING | Event-based clearing |

**Caching Targets:**
- Tenant configurations (TTL: 5 minutes)
- User permissions (TTL: 1 minute)
- Package definitions (TTL: 10 minutes)
- Dashboard metrics (TTL: 30 seconds)

#### Sprint 16: Database Optimization
**Status:** PENDING
**Priority:** HIGH
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Index optimization | PENDING | Query performance |
| Query analysis | PENDING | N+1 detection |
| Connection pooling | PENDING | Async pool config |
| Read replicas | PENDING | Read scaling |
| Partitioning strategy | PENDING | Large table handling |

---

### Phase 8: Security Hardening (PENDING)

#### Sprint 17: Authentication Enhancement
**Status:** IN PROGRESS
**Priority:** CRITICAL
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| 2FA TOTP implementation | COMPLETED | pyotp + QR setup, recovery codes, challenge login flow |
| Password policy enforcement | PENDING | Complexity, history |
| Session management | PENDING | Device tracking, logout all |
| Brute force protection | PENDING | Account lockout |
| IP whitelist/blacklist | PENDING | Access control |

#### Sprint 18: API Security
**Status:** PENDING
**Priority:** CRITICAL
**Estimated Duration:** 1 week

| Task | Status | Notes |
|------|--------|-------|
| Rate limiting per tenant | PENDING | Tier-based limits |
| Request signing | PENDING | Webhook validation |
| API key management | PENDING | Machine-to-machine auth |
| Audit logging | PENDING | Security events |
| Data encryption | PENDING | Sensitive field encryption |

---

### Phase 9: Advanced Analytics (PARTIALLY COMPLETED)

#### Sprint 19: ML-Powered Analytics
**Status:** PARTIALLY COMPLETED
**Priority:** LOW
**Estimated Duration:** 2 weeks

| Task | Status | Notes |
|------|--------|-------|
| Revenue forecasting | COMPLETED | scikit-learn models |
| Customer churn prediction | PENDING | Risk scoring |
| Usage pattern analysis | PENDING | Anomaly detection |
| Recommendation engine | PENDING | Package suggestions |
| Predictive maintenance | PENDING | Router health |

#### Sprint 20: Reporting Enhancement
**Status:** COMPLETED
**Duration:** Completed

| Task | Status | Notes |
|------|--------|-------|
| PDF report generation | COMPLETED | ReportLab + WeasyPrint |
| Excel exports | COMPLETED | OpenPyXL |
| CSV exports | COMPLETED | Pandas/Polars |
| Scheduled reports | COMPLETED | Celery tasks |
| Email delivery | COMPLETED | Automated sending |

---

### Phase 10: Testing & Quality (PARTIALLY COMPLETED)

#### Sprint 21: Test Coverage
**Status:** PARTIALLY COMPLETED
**Priority:** HIGH
**Estimated Duration:** 2 weeks

| Task | Status | Notes |
|------|--------|-------|
| Unit tests (services) | 40% | Pytest + fixtures |
| Integration tests (API) | 30% | TestClient |
| E2E tests | 10% | Full workflow tests |
| Load testing | PENDING | Locust/k6 |
| Security testing | PENDING | OWASP checks |

**Coverage Goals:**
- Services: 80% minimum
- API endpoints: 90% minimum
- Critical paths: 100%

---

## Implementation Priority Matrix

### CRITICAL (Must Complete)
1. **Multi-Tenancy Foundation** (Sprint 9-10)
   - Tenant isolation is fundamental for SaaS operation
   - Blocks all tenant-specific features

2. **Security Hardening** (Sprint 17-18)
   - 2FA for admin accounts
   - Rate limiting per tenant
   - Audit logging

### HIGH Priority
3. **Branding & Customization** (Sprint 11-12)
   - Tenant branding differentiation
   - Captive portal customization

4. **Performance Optimization** (Sprint 15-16)
   - Caching for scalability
   - Database optimization

### MEDIUM Priority
5. **Payment Enhancement** (Sprint 13-14)
   - Paystack for non-Kenya markets
   - Advanced payment features

### LOW Priority
6. **Advanced Analytics** (Sprint 19)
   - ML features are nice-to-have
   - Can be phased in later

---

## API Endpoint Summary

### Implemented Endpoints: 180+

| Module | Endpoints | Status |
|--------|-----------|--------|
| Authentication | 15 | COMPLETED |
| Users | 20 | COMPLETED |
| Routers | 25 | COMPLETED |
| Provisioning | 15 | COMPLETED |
| Plans | 12 | COMPLETED |
| Subscriptions | 18 | COMPLETED |
| Billing | 22 | COMPLETED |
| Payments/M-PESA | 15 | COMPLETED |
| Notifications | 18 | COMPLETED |
| Reports | 12 | COMPLETED |
| Configuration | 10 | COMPLETED |
| Licences | 10 | COMPLETED |
| Support | 8 | COMPLETED |

### Pending Endpoints: ~40

| Module | Endpoints | Status |
|--------|-----------|--------|
| Tenants | 15 | PENDING |
| Branding | 10 | PENDING |
| Captive Portal | 12 | PARTIAL (6/12 done) |
| Voucher Management | 6 | COMPLETED |
| Paystack | 7 | PENDING |

---

## Database Schema Status

### Implemented Tables: 40+
- users, roles, permissions
- routers, router_devices, provisioning_sessions
- plans, subscriptions, invoices, payments
- notifications, notification_templates
- licences, sms_credits
- tickets, ticket_actions
- configurations, audit_logs

### Pending Tables: ~10
- tenants, tenant_settings
- branding_configurations
- captive_portal_templates
- api_keys, rate_limits

---

## Background Tasks (Celery)

### Implemented Tasks: 25+
- Billing cycle processing
- Invoice generation
- Payment reminders
- Subscription expiry checks
- Router sync tasks
- Notification delivery
- Report generation
- Session cleanup

### Pending Tasks: ~10
- Tenant usage aggregation
- Multi-tenant billing
- Cross-tenant analytics
- Tenant backup/restore

---

## Verification Checklist

### Backend Health
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- OpenAPI spec: `http://localhost:8000/openapi.json`

### Default Credentials
- Demo: `demo/demo123`
- Admin: `admin/admin123`
- Superuser: `superuser/superuser123`

### Quick Start
1. Activate virtual environment
2. Run migrations: `alembic upgrade head`
3. Seed data: `python -m app.scripts.seed`
4. Start server: `uvicorn app.main:app --reload`

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Multi-tenant data leakage | CRITICAL | Row-level security, testing |
| Payment integration failures | HIGH | Circuit breakers, retries |
| Router API timeouts | MEDIUM | Connection pooling, caching |
| Database performance | MEDIUM | Indexing, query optimization |
| Session hijacking | HIGH | Token rotation, IP validation |

---

## Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| API Response Time (P95) | < 200ms | ~150ms |
| Uptime | 99.9% | N/A (dev) |
| Test Coverage | > 80% | ~40% |
| API Endpoints | 220+ | 195+ |
| Database Tables | 50+ | 40+ |

---

## Timeline Summary

| Phase | Duration | Status |
|-------|----------|--------|
| Phase 1: Foundation | - | COMPLETED |
| Phase 2: Billing | - | COMPLETED |
| Phase 3: Advanced Features | - | COMPLETED |
| Phase 4: Multi-Tenancy | 3 weeks | PENDING |
| Phase 5: Branding | 2 weeks | PENDING |
| Phase 6: Payment Enhancement | 2 weeks | PENDING |
| Phase 7: Performance | 2 weeks | PENDING |
| Phase 8: Security | 2 weeks | PENDING |
| Phase 9: Analytics | 2 weeks | PARTIAL |
| Phase 10: Testing | 2 weeks | PARTIAL |

**Total Remaining:** ~10-12 weeks for 100% completion

---

## Next Actions

1. **Immediate:** Complete Sprint 12 remaining (portal templates, branding assets)
2. **Week 1-2:** Sprint 9-10 (Tenant Foundation & Configuration)
3. **Week 3:** Sprint 11 (Tenant Branding)
4. **Week 4-5:** Sprint 13 (Paystack full integration)
5. **Week 5-6:** Security Hardening (Sprint 17-18)
6. **Week 7-8:** Performance Optimization (Sprint 15-16)
7. **Week 9-10:** Testing & Documentation (Sprint 21)

---

## Recent Changes (Sprint Delta)

### 2FA TOTP — Full Implementation
- **Dependencies**: Added `pyotp>=2.9.0`, `qrcode[pil]>=7.4.0` to `pyproject.toml`.
- **Model**: Added `totp_secret`, `recovery_codes` (JSON), `two_factor_confirmed_at` columns to `UserSettings`.
- **API** (`api/v1/auth/two_factor.py`): New endpoints — GET `/2fa/status`, POST `/2fa/setup` (QR + TOTP secret), POST `/2fa/verify` (confirms setup, generates recovery codes), POST `/2fa/disable` (password-protected), GET `/2fa/recovery-codes` (regenerate), POST `/2fa/authenticate` (login 2FA challenge).
- **Login flow** (`auth.py`): When `two_factor_enabled` + `two_factor_confirmed_at` is set, returns `{requires_2fa: true, temp_token}` instead of tokens. The temp_token is a 5-minute `2fa_challenge` JWT.
- **Security** (`core/security.py`): Added `create_2fa_challenge_token()`.

### IP Bindings — Backend API
- **API** (`api/v1/network/ip_bindings.py`): CRUD endpoints for MikroTik `/ip/hotspot/ip-binding` — list, create, update, delete. Reads/writes directly to router (no local DB model). Supports `regular`, `bypassed`, `blocked` binding types.
- **Route registration** (`network/__init__.py`): Added `/ip-bindings` prefix.

### Bandwidth Unit Conversion Bug Fix
- **`modules/subscriptions/bandwidth_manager.py`**: Fixed `_sync_hotspot_profile()`, `_sync_ppp_profile()`, and `create_user_queue()` — plan stores speeds in Mbps but `format_rate_limit()` expects Kbps. Now multiplies by 1000 at call sites (e.g., 10 Mbps → `10000k` instead of wrong `10k`).

### PPPoE Paystack Callback Fix
- **`api/v1/portal/pppoe.py`**: Added `request: Request` parameter and `callback_url` construction for Paystack redirects in `renew_subscription` endpoint. Mirrors the hotspot portal pattern — uses `request.headers.get('origin')` to build the frontend callback URL.

### 2FA Alembic Migration
- **Migration** (`alembic/versions/a2f8c94d1e3b_add_2fa_totp_columns_to_user_settings.py`): Adds `totp_secret` (String 255), `recovery_codes` (JSON), `two_factor_confirmed_at` (DateTime) to `user_settings` table. Revision chain: 7f442b4e719a → a2f8c94d1e3b.

### Production Hardening
- **Logging cleanup** (`core/seed_middleware.py`, `core/security.py`): Replaced all `print()` statements with proper `logging.getLogger(__name__)` calls.
- **Demo account safety** (`core/seed_middleware.py`): Demo accounts and licences now only seeded when `not settings.is_production`.
- **TrustedHostMiddleware** (`main.py`): Now uses configurable `settings.allowed_hosts` instead of hardcoded domains.
- **OpenAPI demo credentials** (`main.py`): Full demo info shown only in development; minimal info in production.
- **Config** (`core/config.py`): Added `allowed_hosts: Optional[str]` setting for TrustedHostMiddleware.

---

*This document is maintained as the single source of truth for backend implementation progress.*
