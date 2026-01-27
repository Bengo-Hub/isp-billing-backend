# SMS Provider Integration Guide

This document describes the SMS provider integrations available in ISP Billing, with **Twilio** as the default provider.

## Supported SMS Providers

| Provider | Coverage | Default | Status |
|----------|----------|---------|--------|
| **Twilio** | Global | ✅ Yes | Production Ready |
| Africa's Talking | Africa | No | Production Ready |
| SMS Global | Global | No | Not Implemented |
| Custom | Any | No | Via Extension |

## Architecture

The SMS system consists of three layers:

1. **SMS Providers** (`app/integrations/sms/`) - Low-level provider implementations
2. **SMS Sending Service** (`app/modules/notifications/sms_sender.py`) - High-level service with credit tracking
3. **SMS Credit Management** (`app/modules/notifications/sms.py`) - Credit accounts and transactions

## Twilio Integration (Default)

Twilio provides global SMS coverage with excellent deliverability and is the recommended default provider.

### Configuration

```bash
# Required
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+15551234567  # E.164 format

# Optional
TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # For advanced routing
TWILIO_STATUS_CALLBACK_URL=https://yourdomain.com/api/v1/sms/webhooks/twilio
```

### Usage

#### Direct Provider Usage

```python
from app.integrations.sms import SMSProviderFactory, SMSProviderConfig
from app.models.sms_credit import SMSProviderType

# Create provider
provider = await SMSProviderFactory.create(
    provider_type=SMSProviderType.TWILIO,
    credentials={
        "account_sid": "ACxxxxxxxx",
        "auth_token": "xxxxxxxx",
        "from_number": "+15551234567",
    },
    default_country_code="+254",
)

# Send SMS
result = await provider.send_sms(
    to="+254712345678",
    message="Your internet package has been renewed.",
)

if result.success:
    print(f"Sent! Message ID: {result.message_id}")
else:
    print(f"Failed: {result.message}")
```

#### High-Level Service (Recommended)

```python
from app.modules.notifications.sms_sender import SMSSendingService

# Initialize with database session
sms_service = SMSSendingService(db)

# Send SMS with credit tracking
result = await sms_service.send_sms(
    to="+254712345678",
    message="Your internet package has been renewed.",
    account_id=1,  # SMS credit account ID
    user_id=1,     # For audit trail
)
```

### Bulk SMS

```python
# Using high-level service
result = await sms_service.send_bulk_sms(
    recipients=["+254712345678", "+254712345679", "+254712345670"],
    message="Service maintenance scheduled for tomorrow.",
    account_id=1,
)

print(f"Sent: {result['successful']}, Failed: {result['failed']}")
```

### Delivery Status

```python
# Check delivery status
status = await provider.get_delivery_status("SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
print(f"Status: {status.status}")
```

### Webhook Handling

```python
from fastapi import APIRouter, Request
from app.modules.notifications.sms_sender import SMSSendingService
from app.models.sms_credit import SMSProviderType

router = APIRouter()

@router.post("/webhooks/twilio")
async def twilio_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.form()
    callback_data = dict(payload)
    
    sms_service = SMSSendingService(db)
    transaction = await sms_service.process_delivery_callback(
        provider_type=SMSProviderType.TWILIO,
        callback_data=callback_data,
    )
    
    return {"status": "received"}
```

## Africa's Talking Integration

Africa's Talking is recommended for African markets due to local carrier relationships and competitive pricing.

### Configuration

```bash
# Required
AFRICASTALKING_USERNAME=your_username
AFRICASTALKING_API_KEY=your_api_key

# Optional
AFRICASTALKING_SENDER_ID=YourCompany  # Requires approval
AFRICASTALKING_SANDBOX=false
```

### Usage

```python
from app.integrations.sms import SMSProviderFactory
from app.models.sms_credit import SMSProviderType

provider = await SMSProviderFactory.create(
    provider_type=SMSProviderType.AFRICASTALKING,
    credentials={
        "username": "your_username",
        "api_key": "your_api_key",
        "sender_id": "YourCompany",  # Optional
        "is_sandbox": False,
    },
    default_country_code="+254",
)

result = await provider.send_sms(
    to="0712345678",  # Will be formatted to +254712345678
    message="Your subscription expires tomorrow.",
)
```

### Bulk SMS (Native Support)

Africa's Talking has native bulk SMS support, which is more efficient than sending individual messages:

```python
# Sends all messages in a single API call
result = await provider.send_bulk_sms(
    recipients=["0712345678", "0723456789", "0734567890"],
    message="Service maintenance tomorrow.",
)

print(f"Total: {result.total}, Successful: {result.successful}")
```

## SMS Credit Management

### Creating an SMS Account

```python
from app.modules.notifications.sms import SMSCreditService
from app.models.sms_credit import SMSProviderType

credit_service = SMSCreditService(db)

account = await credit_service.create_sms_account(
    account_data={
        "account_name": "Main SMS Account",
        "provider_type": SMSProviderType.TWILIO,
        "phone_number": "+254712345678",
        "country_code": "+254",
        "currency": "KES",
        "minimum_balance_threshold": 100,
        "auto_top_up_enabled": True,
        "auto_top_up_amount": 500,
        "auto_top_up_threshold": 50,
        "provider_config": {
            "account_sid": "ACxxxxxxxx",
            "auth_token": "xxxxxxxx",
            "from_number": "+15551234567",
        },
    },
    created_by=user_id,
)
```

### Top-Up Credits

```python
# Create top-up request
top_up = await credit_service.top_up_sms_credit(
    account_id=account.id,
    amount=Decimal("500.00"),
    payment_method="paystack",
    requested_by=user_id,
)

# Process top-up after payment confirmation
await credit_service.process_top_up(
    top_up_id=top_up.id,
    external_transaction_id="PAY-xxxxx",
    approved_by=admin_id,
)
```

### Check Balance

```python
account = await credit_service.get_account_by_id(account_id)
print(f"Balance: {account.current_balance} {account.currency}")
print(f"Low balance: {account.is_low_balance}")
```

## SMS Templates

Store reusable SMS templates:

```python
from app.modules.notifications.templates import SMSTemplateService

template_service = SMSTemplateService(db)

# Create template
template = await template_service.create_template(
    name="subscription_reminder",
    content="Dear {{customer_name}}, your {{package_name}} subscription expires on {{expiry_date}}.",
    variables=["customer_name", "package_name", "expiry_date"],
)

# Render template
message = await template_service.render_template(
    template_name="subscription_reminder",
    context={
        "customer_name": "John",
        "package_name": "Basic Internet",
        "expiry_date": "2024-02-15",
    },
)
# Result: "Dear John, your Basic Internet subscription expires on 2024-02-15."
```

## Provider Health Checks

```python
# Check provider health
sms_service = SMSSendingService(db)
health = await sms_service.get_provider_health(account_id=1)

print(f"Provider: {health['provider']}")
print(f"Status: {health['status']}")
print(f"Balance: {health['balance']} {health.get('currency', 'USD')}")
print(f"Account Balance: {health['account_balance']} {health['account_currency']}")
```

## Error Handling

```python
from app.integrations.sms.base import SMSDeliveryStatus

result = await sms_service.send_sms(...)

if not result.success:
    if result.error_code == "INSUFFICIENT_CREDIT":
        # Top up required
        pass
    elif result.error_code == "INVALID_NUMBER":
        # Bad phone number
        pass
    elif result.status == SMSDeliveryStatus.UNDELIVERED:
        # Number unreachable
        pass
```

## Best Practices

1. **Use credit accounts** - Track SMS spending per organization
2. **Set up auto top-up** - Prevent service interruption
3. **Handle delivery callbacks** - Know when SMS is delivered
4. **Use templates** - Maintain consistent messaging
5. **Format phone numbers** - Always use E.164 format
6. **Monitor balance** - Set low balance alerts

## Rate Limiting

Twilio: ~10 SMS/second (can be increased)
Africa's Talking: ~10 SMS/second (bulk up to 100)

The `SMSSendingService` implements rate limiting automatically for bulk sends.

## Related Documentation

- [Twilio SMS API](https://www.twilio.com/docs/sms)
- [Africa's Talking SMS](https://developers.africastalking.com/docs/sms/overview)
- [Backend Audit](./backend-audit.md)
