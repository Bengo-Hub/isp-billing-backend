# MPESA Integration Guide

This guide provides comprehensive instructions for setting up and using the MPESA Daraja API integration in the ISP Billing System.

## Overview

The MPESA integration follows the official Safaricom Daraja API documentation and provides:
- STK Push payment initiation
- Payment status queries
- Callback processing with signature verification
- Transaction reversals
- Comprehensive error handling and logging

Reference: https://developer.safaricom.co.ke/Documentation

## Setup Instructions

### 1. Obtain MPESA Credentials

1. Register at the [Safaricom Developer Portal](https://developer.safaricom.co.ke/)
2. Create a new app and obtain:
   - Consumer Key
   - Consumer Secret
   - Passkey
   - Shortcode (Paybill/Till Number)

### 2. Download Public Keys

Download the official MPESA public keys from the Safaricom Developer Portal:

**For Sandbox Environment:**
- Download: `mpesa_sandbox_public_key.pem`
- Place in: `backend/app/integrations/keys/`

**For Production Environment:**
- Download: `mpesa_public_key.pem`
- Place in: `backend/app/integrations/keys/`

### 3. Configure Environment Variables

Add the following to your `.env` file:

```env
# MPESA Configuration
MPESA_ENVIRONMENT=sandbox  # or "production"
MPESA_CONSUMER_KEY=your_consumer_key
MPESA_CONSUMER_SECRET=your_consumer_secret
MPESA_PASSKEY=your_passkey
MPESA_SHORTCODE=your_shortcode
MPESA_CALLBACK_URL=https://yourdomain.com/api/v1/mpesa/callback
```

### 4. Database Configuration

The MPESA integration uses the existing billing system tables:
- `payments` - Stores payment records
- `users` - User information for phone numbers

## API Endpoints

### 1. Initiate Payment

**POST** `/api/v1/mpesa/initiate-payment`

Initiates an STK Push payment request.

**Request Body:**
```json
{
  "amount": 1000,
  "account_reference": "ISP123456",
  "description": "Internet Bill"
}
```

**Response:**
```json
{
  "success": true,
  "payment_id": 123,
  "checkout_request_id": "ws_CO_123456789",
  "amount": 1000,
  "phone_number": "254712345678",
  "message": "Payment request sent to your phone"
}
```

### 2. Query Payment Status

**GET** `/api/v1/mpesa/payment-status/{checkout_request_id}`

Queries the status of a payment using the checkout request ID.

**Response:**
```json
{
  "success": true,
  "payment_id": 123,
  "status": "completed",
  "amount": 1000,
  "mpesa_response": {
    "ResultCode": 0,
    "ResultDesc": "The service request is processed successfully"
  }
}
```

### 3. Process Callback

**POST** `/api/v1/mpesa/callback`

Processes MPESA callbacks with signature verification.

**Note:** This endpoint is called by MPESA servers and should be publicly accessible.

### 4. Get Transaction Status

**GET** `/api/v1/mpesa/transaction-status/{transaction_id}`

Queries the status of a specific transaction from MPESA.

### 5. Reverse Payment

**POST** `/api/v1/mpesa/reverse-payment`

Reverses a completed payment.

**Request Body:**
```json
{
  "payment_id": 123,
  "reason": "Customer requested refund"
}
```

### 6. Get Payment Statistics

**GET** `/api/v1/mpesa/statistics`

Retrieves comprehensive MPESA payment statistics.

## Security Features

### 1. Signature Verification

All MPESA callbacks are verified using the official Safaricom public key:
- Cryptographic signature verification using RSA-SHA256
- Fallback to basic validation if public key is not available
- Comprehensive logging of verification attempts

### 2. Input Validation

- Phone number format validation (Kenyan format)
- Amount validation (1-150,000 KES)
- Account reference length validation (max 12 characters)
- Description length validation (max 13 characters)

### 3. Error Handling

- Comprehensive error handling with custom exceptions
- Retry logic with exponential backoff
- Timeout management (30 seconds)
- Detailed logging for debugging

## Usage Examples

### Python Service Usage

```python
from app.modules.billing import MpesaService

# Initialize service
mpesa_service = MpesaService(db, environment="sandbox")

# Initiate payment
result = await mpesa_service.initiate_payment(
    user=user,
    amount=1000,
    account_reference="ISP123456",
    description="Internet Bill"
)

# Query payment status
status = await mpesa_service.query_payment_status(
    checkout_request_id="ws_CO_123456789"
)

# Process callback
callback_result = await mpesa_service.process_callback(callback_data)
```

### Direct API Usage

```python
from app.integrations.mpesa import MpesaAPI

# Initialize API client
mpesa_api = MpesaAPI(environment="sandbox")

# Get access token
token = await mpesa_api.get_access_token()

# Initiate STK Push
result = await mpesa_api.stk_push(
    phone_number="254712345678",
    amount=1000,
    account_reference="ISP123456",
    transaction_desc="Internet Bill"
)
```

## Error Codes

### Validation Errors (400)
- `ValidationError`: Input validation failed
- `Missing required fields`: Required parameters missing
- `Invalid phone number format`: Phone number format invalid
- `Amount out of range`: Amount not within 1-150,000 KES

### External Service Errors (502)
- `ExternalServiceError`: MPESA API error
- `Authentication failed`: Invalid credentials
- `API request timeout`: Request timed out
- `API request failed`: Network or server error

### Billing Errors (500)
- `BillingError`: Internal billing system error
- `Payment not found`: Payment record not found
- `Database error`: Database operation failed

## Monitoring and Logging

### Log Levels
- **INFO**: Successful operations, payment completions
- **WARNING**: Signature verification failures, missing keys
- **ERROR**: API failures, validation errors
- **DEBUG**: Detailed operation information

### Key Metrics
- Payment success rate
- API response times
- Error rates by type
- Signature verification success rate

## Production Deployment

### 1. Security Checklist
- [ ] Public keys properly installed
- [ ] Environment variables secured
- [ ] Callback URL is HTTPS
- [ ] Rate limiting configured
- [ ] Monitoring alerts set up

### 2. Performance Considerations
- Public key caching in memory
- Database connection pooling
- Request timeout configuration
- Retry logic tuning

### 3. Monitoring Setup
- Payment success rate monitoring
- API response time monitoring
- Error rate alerting
- Signature verification monitoring

## Troubleshooting

### Common Issues

1. **Signature Verification Fails**
   - Check if public key file exists
   - Verify public key format (PEM)
   - Check file permissions

2. **Payment Initiation Fails**
   - Verify credentials are correct
   - Check phone number format
   - Ensure amount is within limits

3. **Callback Not Received**
   - Verify callback URL is accessible
   - Check firewall settings
   - Ensure HTTPS is used

### Debug Mode

Enable debug logging by setting:
```env
LOG_LEVEL=DEBUG
```

This will provide detailed information about:
- API requests and responses
- Signature verification process
- Database operations
- Error details

## Support

For technical support:
1. Check the logs for detailed error information
2. Verify configuration against this guide
3. Test with sandbox environment first
4. Contact Safaricom support for API issues

## References

- [Safaricom Developer Portal](https://developer.safaricom.co.ke/)
- [MPESA Daraja API Documentation](https://developer.safaricom.co.ke/Documentation)
- [Official MPESA Integration Guide](https://developer.safaricom.co.ke/Documentation)
