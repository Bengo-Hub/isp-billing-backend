# Payment Gateway Integration Guide

This document describes the payment gateway integrations available in ISP Billing, focusing on **Paystack** as the default payment gateway.

## Supported Payment Gateways

| Gateway | Type | Default | Status |
|---------|------|---------|--------|
| **Paystack** | Card, Mobile Money, Bank Transfer | ✅ Yes | Production Ready |
| M-PESA | Mobile Money (STK Push) | No | Production Ready |
| Manual | Bank Transfer, Cash | No | Production Ready |

## Paystack Integration

Paystack is the default payment gateway, supporting:
- Card payments (Visa, Mastercard)
- Mobile Money (M-PESA, MTN, Airtel, etc.)
- Bank transfers
- Recurring subscriptions
- Payouts to bank accounts and mobile money

### Configuration

Set the following environment variables:

```bash
# Paystack API Keys
PAYSTACK_SECRET_KEY=sk_live_xxxxx  # or sk_test_xxxxx for testing
PAYSTACK_PUBLIC_KEY=pk_live_xxxxx  # or pk_test_xxxxx for testing

# Optional: Webhook configuration
PAYSTACK_WEBHOOK_SECRET=whsec_xxxxx

# Default settings
PAYSTACK_CURRENCY=KES
PAYSTACK_CALLBACK_URL=https://yourdomain.com/api/v1/payments/paystack/callback
```

### Available Methods

#### Transaction Initialization

```python
from app.integrations.payment_gateways import PaymentGatewayFactory
from app.models.payment_gateway import GatewayType

gateway = await PaymentGatewayFactory.create(GatewayType.PAYSTACK, config)

result = await gateway.initiate_payment(
    amount=Decimal("1000.00"),  # KES 1000
    phone_number="+254712345678",
    reference="INV-001",
    description="Internet subscription",
    callback_url="https://yourdomain.com/callback",
    metadata={"customer_id": "123", "email": "customer@example.com"}
)

if result.success:
    # Redirect customer to checkout_url
    print(f"Checkout URL: {result.checkout_url}")
```

#### Transaction Verification

```python
result = await gateway.verify_payment("INV-001")

if result.success and result.status == PaymentStatus.COMPLETED:
    print(f"Payment successful: {result.amount} {result.currency}")
```

#### Subscription Management

```python
# Create a subscription plan
plan = await gateway.create_plan(
    name="Basic Internet",
    amount=Decimal("2000.00"),
    interval="monthly",
    currency="KES",
    description="Basic internet package - 10Mbps",
    send_invoices=True,
    send_sms=True,
)

plan_code = plan["data"]["plan_code"]

# Create subscription for customer
subscription = await gateway.create_subscription(
    email="customer@example.com",
    plan_code=plan_code,
    authorization_code="AUTH_xxx",  # From first successful payment
)

# Get subscription details
details = await gateway.get_subscription(subscription["data"]["subscription_code"])

# Disable subscription
await gateway.disable_subscription(
    subscription_code="SUB_xxx",
    email_token="token_from_email",
)
```

#### Recurring Payments (Charge Authorization)

```python
# Charge a saved card
result = await gateway.charge_authorization(
    email="customer@example.com",
    amount=Decimal("2000.00"),
    authorization_code="AUTH_xxx",  # Saved from first payment
    reference="RENEWAL-001",
    metadata={"subscription_id": "123"},
)
```

#### Transfers / Payouts

```python
# 1. Create a transfer recipient
recipient = await gateway.create_transfer_recipient(
    recipient_type="mobile_money",  # or "nuban" for bank
    name="John Doe",
    account_number="0712345678",  # Mobile number or bank account
    bank_code="MPESA",  # From list_mobile_money_providers()
    currency="KES",
    description="ISP payout",
)

recipient_code = recipient["data"]["recipient_code"]

# 2. Initiate transfer
transfer = await gateway.initiate_transfer(
    amount=Decimal("5000.00"),
    recipient_code=recipient_code,
    reference="PAYOUT-001",
    reason="Monthly payout to ISP",
)

# 3. Verify transfer
status = await gateway.verify_transfer("PAYOUT-001")

# Bulk transfers
transfers = [
    {"amount": 100000, "recipient": "RCP_xxx", "reference": "PAY-001"},
    {"amount": 200000, "recipient": "RCP_yyy", "reference": "PAY-002"},
]
bulk_result = await gateway.initiate_bulk_transfer(transfers, currency="KES")
```

#### Bank and Mobile Money Provider Lists

```python
# Get banks for a country
banks = await gateway.list_banks(country="kenya")
for bank in banks["data"]:
    print(f"{bank['name']}: {bank['code']}")

# Get mobile money providers
providers = await gateway.list_mobile_money_providers(country="kenya")
for provider in providers["data"]:
    print(f"{provider['name']}: {provider['code']}")

# Resolve bank account name
account = await gateway.resolve_account_number(
    account_number="1234567890",
    bank_code="058",  # GTBank
)
print(f"Account name: {account['data']['account_name']}")
```

### Webhook Handling

Paystack sends webhooks for payment events. Configure your webhook endpoint:

```python
from fastapi import APIRouter, Request, HTTPException
from app.integrations.payment_gateways.paystack import PaystackGateway

router = APIRouter()

@router.post("/webhooks/paystack")
async def paystack_webhook(request: Request):
    # Get raw body for signature verification
    body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    
    # Verify signature (implemented in PaystackGateway)
    gateway = await PaymentGatewayFactory.create(GatewayType.PAYSTACK, config)
    
    payload = await request.json()
    result = await gateway.process_callback(payload)
    
    if result.success:
        # Handle successful payment
        pass
    
    return {"status": "received"}
```

### Webhook Events

| Event | Description |
|-------|-------------|
| `charge.success` | Payment completed successfully |
| `charge.failed` | Payment failed |
| `transfer.success` | Transfer completed |
| `transfer.failed` | Transfer failed |
| `subscription.create` | New subscription created |
| `subscription.disable` | Subscription disabled |
| `invoice.create` | Invoice generated |
| `invoice.payment_failed` | Invoice payment failed |

## M-PESA Integration

M-PESA is available for Kenyan payments via STK Push.

### Configuration

```bash
MPESA_ENVIRONMENT=production  # or sandbox
MPESA_CONSUMER_KEY=xxx
MPESA_CONSUMER_SECRET=xxx
MPESA_PASSKEY=xxx
MPESA_SHORTCODE=174379
MPESA_CALLBACK_URL=https://yourdomain.com/api/v1/payments/mpesa/callback
```

### STK Push

```python
from app.integrations.mpesa import MpesaAPI

mpesa = MpesaAPI()
result = await mpesa.stk_push(
    phone_number="254712345678",
    amount=1000,
    account_reference="INV-001",
    description="Internet subscription",
)
```

## Best Practices

1. **Always verify payments server-side** - Never trust client-side payment confirmations
2. **Use idempotency keys** - Prevent duplicate payments with unique references
3. **Handle webhooks** - Process webhooks for real-time payment updates
4. **Store authorization codes** - Save card authorizations for recurring payments
5. **Monitor failures** - Track failed payments and implement retry logic
6. **Test in sandbox** - Always test integrations in sandbox/test mode first

## Error Handling

```python
from app.integrations.payment_gateways.base import PaymentStatus

result = await gateway.initiate_payment(...)

if not result.success:
    if result.status == PaymentStatus.FAILED:
        # Handle permanent failure
        log_error(result.message)
    elif result.status == PaymentStatus.TIMEOUT:
        # Retry the payment
        pass
```

## Related Documentation

- [Paystack API Docs](https://paystack.com/docs/api/)
- [M-PESA Daraja API](https://developer.safaricom.co.ke/Documentation)
- [Backend Audit](./backend-audit.md)
