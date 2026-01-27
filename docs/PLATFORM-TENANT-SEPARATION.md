# Platform vs Tenant Settings - Separation of Concerns

## Overview

This document explains the clear separation between **Platform-level settings** and **Tenant-specific settings** in the ISP Billing system. This separation ensures proper access control, data isolation, and maintainability.

---

## Design Principles

### ✅ **Platform Settings**
- **Scope**: Apply to ALL tenants/ISP providers across the entire platform
- **Access**: Platform administrators/superusers ONLY
- **Location**: `/platform/settings` route
- **Examples**: Payment gateway API credentials, SMS provider configuration, platform-wide integrations

### ✅ **Tenant Settings**
- **Scope**: Apply ONLY to the specific ISP provider/tenant
- **Access**: Tenant administrators and authorized users
- **Location**: `/dashboard/settings` route (within tenant dashboard)
- **Examples**: Payout bank details, notification templates, tenant-specific preferences

---

## Configuration Breakdown

### **Platform Settings** (`/platform/settings`)

#### General Tab
- ✅ Platform name
- ✅ Support email
- ✅ Default trial days
- ✅ Default currency

#### Domain Tab
- ✅ Portal base domain (tenant subdomains)
- ✅ API domain

#### **Integrations Tab** ⭐ **NEW**
- ✅ **M-Pesa Daraja API Configuration**
  - Consumer Key
  - Consumer Secret
  - Passkey
  - Shortcode
  - Environment (sandbox/production)
- ✅ **SMS Gateway Configuration**
  - Provider selection (Africa's Talking, Twilio, Custom)
  - API Key
  - Username/Account SID
  - Sender ID
- ✅ **Webhook & Callback URLs**
  - M-Pesa validation, confirmation, callback URLs
  - Paystack webhook URLs
  - Auto-configured endpoints for all integrations

#### Paystack Tab
- ✅ Public Key (for platform subscription billing)
- ✅ Secret Key
- ✅ Webhook Secret

#### Email Tab
- ✅ SMTP configuration (platform-wide email sending)
- ✅ From email/name

#### Notifications Tab
- ✅ Platform notification preferences

#### Security Tab
- ✅ Session timeout
- ✅ Max login attempts
- ✅ 2FA requirements for platform admins

---

### **Tenant Settings** (`/dashboard/settings`)

#### General Settings Tab
- ✅ Company logo
- ✅ Terms & conditions text
- ✅ Company information

#### **Payments Tab** (Tenant-Specific)
- ✅ **Payment Information**
  - Payment gateway selection
  - Bank paybill number
  - Bank account number
- ✅ **Payout Configuration** (Tenant receives payouts)
  - Payout schedule (daily, weekly, monthly)
  - Payout day/time
  - Minimum payout amount
  - Recipient account details (bank or mobile money)
- ❌ **REMOVED**: M-Pesa API credentials (moved to Platform)
- ❌ **REMOVED**: Integration webhook URLs (moved to Platform)

#### PPPoE Tab
- ✅ Server pool configuration
- ✅ DNS servers
- ✅ RADIUS integration

#### Hotspot Tab
- ✅ Service configuration
- ✅ Captive portal settings

#### SMS Gateway Tab
- ✅ SMS template customization for this tenant
- ✅ SMS balance tracking
- ⚠️ Gateway credentials configured at platform level

#### Notifications Tab
- ✅ SMS/Email template customization
- ✅ Notification triggers for this tenant

---

## Architecture Diagrams

### Before (❌ Problematic)
```
┌─────────────────────────────────────────┐
│         Tenant Settings                 │
│         /dashboard/settings             │
│                                         │
│  • M-Pesa Credentials (WRONG!)         │
│  • SMS Gateway API Keys (WRONG!)       │
│  • Integration URLs (WRONG!)           │
│  • Payout Configuration (Correct)      │
└─────────────────────────────────────────┘
```

### After (✅ Correct)
```
┌─────────────────────────────────────────┐
│      Platform Settings                  │
│      /platform/settings                 │
│      (Platform Admins Only)             │
│                                         │
│  Integrations Tab:                      │
│  • M-Pesa Daraja API ✅                │
│  • SMS Gateway (Twilio/AT) ✅          │
│  • Webhook URLs ✅                     │
└─────────────────────────────────────────┘
                    │
                    │ Provides Services
                    ▼
┌─────────────────────────────────────────┐
│      Tenant Settings                    │
│      /dashboard/settings                │
│      (Tenant Admins/Users)              │
│                                         │
│  Payments Tab:                          │
│  • Payment Info (Bank Details) ✅       │
│  • Payout Configuration ✅              │
│  • Notice: Gateway managed by platform  │
└─────────────────────────────────────────┘
```

---

## Data Flow

### Payment Processing Flow
```
Customer Payment Request
        │
        ▼
Tenant Dashboard → Uses Platform-Configured Gateway
                              │
                              ▼
              ┌───────────────────────────────┐
              │   Platform Integration        │
              │   (M-Pesa/Paystack)          │
              │   Credentials: Platform-level │
              └───────────────────────────────┘
                              │
                              ▼
              Payment Webhook → Platform Backend
                              │
                              ▼
              Record Payment → Tenant Balance
                              │
                              ▼
           Scheduled Payout → Tenant Bank Account
                              (Using Tenant Payout Config)
```

---

## Access Control

### Platform Settings Access
- **Permission**: `platform.admin` or `superuser`
- **Check**: User must have platform-level admin role
- **Frontend Route**: `/platform/settings`
- **Backend Endpoints**: `/api/v1/platform/*`, `/api/v1/integrations/*`

### Tenant Settings Access
- **Permission**: `tenant.admin` or specific tenant permissions
- **Check**: User must belong to the tenant organization
- **Frontend Route**: `/dashboard/settings`
- **Backend Endpoints**: `/api/v1/tenant/*`, `/api/v1/settings/*`

---

## Migration Guide

### Changes Made

#### Frontend Changes
1. **Created** new "Integrations" tab in `/platform/settings/page.tsx`
2. **Moved** M-Pesa configuration from tenant to platform settings
3. **Moved** Integration URLs from tenant to platform settings
4. **Simplified** `/dashboard/settings` (tenant) to remove platform configs
5. **Added** informational notice in tenant settings directing to platform admin

#### What Tenants Now See
- ✅ Can configure payout bank details
- ✅ Can see payment information section
- ✅ Notice that gateway credentials are managed by platform
- ❌ Cannot see M-Pesa API credentials
- ❌ Cannot see integration webhook URLs

#### What Platform Admins Now See
- ✅ Dedicated "Integrations" tab with all gateway configurations
- ✅ M-Pesa Daraja API credentials form
- ✅ SMS Gateway provider selection and configuration
- ✅ Copy-to-clipboard webhook URLs for M-Pesa and Paystack
- ✅ Test connection buttons for each integration

---

## Backend Endpoints Structure

### Platform Endpoints (`/api/v1/platform/`)
```
GET    /api/v1/platform/settings               # Platform-wide settings
PUT    /api/v1/platform/settings/{key}         # Update platform setting
GET    /api/v1/integrations/mpesa/config       # M-Pesa configuration
PUT    /api/v1/integrations/mpesa/config       # Update M-Pesa config
POST   /api/v1/integrations/mpesa/test         # Test M-Pesa connection
GET    /api/v1/integrations/urls               # Get all integration URLs
```

### Tenant Endpoints (`/api/v1/tenant/`)
```
GET    /api/v1/tenant/settings                 # Tenant-specific settings
PUT    /api/v1/tenant/settings/{key}           # Update tenant setting
GET    /api/v1/tenant/payout-config            # Tenant payout configuration
PUT    /api/v1/tenant/payout-config            # Update payout config
```

---

## Benefits of This Separation

### 🔐 Security
- Platform credentials not exposed to tenants
- API keys and secrets isolated at platform level
- Reduced attack surface for tenant users

### 🎯 Clarity
- Clear distinction between platform and tenant responsibilities
- Easier onboarding for new tenants (less configuration)
- Reduced confusion about what settings apply where

### 🔧 Maintainability
- Centralized integration management
- Single point of update for gateway credentials
- Easier to add new payment gateways (platform-level change)

### 📈 Scalability
- Platform admin can configure once, applies to all tenants
- Tenants don't need individual API credentials
- Simplified tenant onboarding process

---

## Testing Checklist

### Platform Settings
- [ ] Navigate to `/platform/settings` as platform admin
- [ ] Verify "Integrations" tab is visible
- [ ] Configure M-Pesa credentials and test connection
- [ ] Configure SMS gateway and send test SMS
- [ ] Copy webhook URLs and verify format

### Tenant Settings
- [ ] Navigate to `/dashboard/settings` as tenant admin
- [ ] Verify Payments tab shows payment info and payout config
- [ ] Verify M-Pesa credentials section is REMOVED
- [ ] Verify integration URLs section is REMOVED
- [ ] Verify informational notice about platform-managed gateways is present
- [ ] Configure payout settings and save successfully

### Access Control
- [ ] Tenant users cannot access `/platform/settings`
- [ ] Platform admins can access both `/platform/settings` and `/dashboard/settings`
- [ ] API endpoints enforce proper permission checks

---

## Troubleshooting

### Tenant Can't See Payment Options
**Solution**: Payment gateways are configured at platform level. Contact platform administrator to enable M-Pesa/Paystack integration.

### Webhook URLs Not Working
**Solution**: Ensure webhook URLs are registered in the payment provider's dashboard exactly as shown in Platform Settings → Integrations tab.

### M-Pesa Test Connection Fails
**Solution**: Verify all credentials (Consumer Key, Secret, Passkey, Shortcode) are correct in Platform Settings → Integrations tab. Check environment is set correctly (sandbox vs production).

---

## Future Enhancements

- [ ] Add SMS provider switching per tenant (while using platform credentials)
- [ ] Add payment gateway selection per tenant (from platform-configured options)
- [ ] Add integration health monitoring dashboard
- [ ] Add webhook event logs and debugging tools
- [ ] Add platform-level analytics for integration usage across tenants

---

**Last Updated**: January 27, 2026  
**Author**: System Architect  
**Status**: ✅ Implemented and Documented
