# Payout Configuration

**Version:** 1.0  
**Date:** January 27, 2026

## Overview

The Payout Configuration feature allows ISP providers to configure how and when collected payments from their Hotspot/PPPoE clients are disbursed to their settlement accounts. This feature integrates with Paystack's Transfer API for automated payouts.

## Payout Schedule Types

| Schedule Type | Description | Configuration |
|---------------|-------------|---------------|
| **Instant** | Payout immediately when payment is received on Paystack | No additional config needed |
| **Daily (COB)** | Payout at end of business day | `payout_time` (e.g., "17:00") |
| **Weekly** | Payout on a specific day each week | `payout_day` (1-7, Monday=1), `payout_time` |
| **Monthly** | Payout on a specific date each month | `payout_day` (1-28), `payout_time` |

## Supported Recipient Types (Paystack Transfer Recipients)

All payout recipient types are based on Paystack's supported transfer recipient types:

### Enabled by Default

| Type | Name | Currency | Countries | Required Fields |
|------|------|----------|-----------|-----------------|
| `kepss` | Kenya Bank Account (KEPSS) | KES | Kenya | bank_code, account_number, account_name |
| `mobile_money` | Mobile Money (M-PESA) | KES/GHS | Kenya, Ghana | bank_code, mobile_number, account_name |
| `mobile_money_business` | Mobile Money Business (Paybill/Till) | KES | Kenya | bank_code, account_number, account_name |
| `nuban` | Nigeria Bank Account (NUBAN) | NGN | Nigeria | bank_code, account_number, account_name |
| `ghipss` | Ghana Bank Account (GHIPSS) | GHS | Ghana | bank_code, account_number, account_name |
| `basa` | South Africa Bank Account (BASA) | ZAR | South Africa | bank_code, account_number, account_name |

### Disabled by Default (Requires Superuser)

| Type | Name | Reason |
|------|------|--------|
| `authorization` | Card Payout | Requires prior card authorization code |

## Mobile Money Provider Codes (Kenya)

| Code | Provider | Description |
|------|----------|-------------|
| `MPESA` | M-PESA | Individual M-PESA users |
| `MPPAYBILL` | M-PESA Paybill | Business Paybill numbers |
| `MPTILL` | M-PESA Till | Business Till numbers |

## Mobile Money Provider Codes (Ghana)

| Code | Provider |
|------|----------|
| `MTN` | MTN Mobile Money |
| `VODAFONE` | Vodafone Cash |

## API Endpoints

### Get Recipient Types
```
GET /api/v1/tenant/payment-gateways/payout/recipient-types
```

Returns list of available payout recipient types with their requirements and enabled status.

### Get Schedule Types
```
GET /api/v1/tenant/payment-gateways/payout/schedule-types
```

Returns list of available payout schedule types with day options where applicable.

### Get Payout Configuration
```
GET /api/v1/tenant/payment-gateways/payout/config
```

Returns the current payout configuration for the organization, or `null` if not configured.

### Create Payout Configuration
```
POST /api/v1/tenant/payment-gateways/payout/config
Content-Type: application/json

{
  "schedule_type": "daily",
  "payout_time": "17:00",
  "recipient_type": "kepss",
  "bank_code": "063",
  "bank_name": "Diamond Trust Bank",
  "account_number": "1234567890",
  "account_name": "ISP Company Ltd",
  "currency": "KES",
  "min_payout_amount": 1000
}
```

### Update Payout Configuration
```
PUT /api/v1/tenant/payment-gateways/payout/config
Content-Type: application/json

{
  "schedule_type": "weekly",
  "payout_day": 5,
  "payout_time": "18:00"
}
```

### Delete Payout Configuration
```
DELETE /api/v1/tenant/payment-gateways/payout/config
```

## Database Models

### PayoutConfig
Stores payout configuration per organization (one config per org).

| Field | Type | Description |
|-------|------|-------------|
| id | Integer | Primary key |
| organization_id | Integer | FK to organizations (unique) |
| schedule_type | Enum | instant, daily, weekly, monthly |
| payout_day | Integer | 1-7 (weekly) or 1-28 (monthly) |
| payout_time | String | HH:MM format (e.g., "17:00") |
| recipient_type | Enum | kepss, mobile_money, nuban, etc. |
| recipient_code | String | Paystack recipient code (RCP_xxx) |
| bank_code | String | Bank or mobile money provider code |
| bank_name | String | Display name of bank |
| account_number | String | Bank account number |
| account_name | String | Name on account |
| mobile_number | String | For mobile money recipients |
| currency | String | KES, NGN, GHS, ZAR |
| min_payout_amount | Decimal | Minimum balance before payout |
| is_active | Boolean | Whether payouts are enabled |
| is_verified | Boolean | Whether recipient is verified |

### PayoutRecord
Tracks executed payout transactions.

| Field | Type | Description |
|-------|------|-------------|
| id | Integer | Primary key |
| organization_id | Integer | FK to organizations |
| payout_config_id | Integer | FK to payout_configs |
| reference | String | Unique payout reference |
| transfer_code | String | Paystack transfer code |
| amount | Decimal | Payout amount |
| fee | Decimal | Payout fee |
| net_amount | Decimal | Amount after fee |
| period_start | DateTime | Start of payment period |
| period_end | DateTime | End of payment period |
| transaction_count | Integer | Number of transactions included |
| status | Enum | pending, processing, completed, failed, cancelled |

## Frontend Integration

### Settings Tab
Payout configuration is available in **Settings > Payments** tab as a new "Payout Configuration" card.

### Features
- Schedule type selection with description
- Dynamic day selector for weekly/monthly schedules
- Recipient type selection (Paystack-supported only)
- Bank account or mobile money input
- Minimum payout threshold
- Verification status indicator
- Payout statistics display

### Hooks (features/settings/gateways.ts)
```typescript
usePayoutRecipientTypes()  // Get available recipient types
usePayoutScheduleTypes()   // Get available schedule types
usePayoutConfig()          // Get current config
useSavePayoutConfig()      // Create new config
useUpdatePayoutConfig()    // Update existing config
useDeletePayoutConfig()    // Delete config
```

## Security Considerations

1. **ISP Admin Only**: All payout endpoints require `require_isp_admin` authentication
2. **Organization Scoped**: Each organization can only see/modify their own config
3. **Verification Required**: Payouts are marked as pending verification until confirmed
4. **Sensitive Data**: Account numbers should be partially masked in UI after save
5. **Audit Trail**: All payout attempts logged in PayoutRecord

## Future Enhancements

- [ ] Auto-create Paystack transfer recipient on config save
- [ ] Account verification flow (test transfer)
- [ ] Payout scheduling worker/cron job
- [ ] Webhook handling for payout status updates
- [ ] Payout failure notifications
- [ ] Superuser override for disabled recipient types
