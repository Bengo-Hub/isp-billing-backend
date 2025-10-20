# ISP Billing System - API Documentation

## Overview

The ISP Billing System provides a comprehensive REST API for managing internet service provider operations, including user management, router integration, billing, and payment processing.

## Base URL

- **Development**: `http://localhost:8000`
- **Production**: `https://yourdomain.com`

## Authentication

The API uses JWT (JSON Web Tokens) for authentication. Include the token in the Authorization header:

```
Authorization: Bearer <your_access_token>
```

### Getting Access Token

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=your_username&password=your_password
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

## API Endpoints

### Device Provisioning Endpoints

#### Start Provisioning Workflow
```http
POST /api/v1/provisioning/workflow
Content-Type: application/json
Authorization: Bearer <token>

{
  "router_id": 1,
  "service_type": "hotspot",
  "configuration": {
    "hotspot_name": "ISP-Hotspot",
    "interface": "ether2",
    "ip_pool_start": "172.31.1.1",
    "ip_pool_end": "172.31.1.254",
    "gateway": "172.31.1.1",
    "enable_anti_sharing": true
  },
  "priority": "normal",
  "auto_start": true,
  "backup_current_config": true,
  "rollback_on_failure": true
}
```

**Response:**
```json
{
  "session_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "in_progress",
  "message": "Provisioning workflow started successfully",
  "estimated_duration_minutes": 20,
  "steps": [
    {"step": "connection", "description": "Device connection and verification"},
    {"step": "configuration", "description": "Basic router configuration"},
    {"step": "service_setup", "description": "hotspot service setup"}
  ]
}
```

#### Get Provisioning Status
```http
GET /api/v1/provisioning/sessions/{session_id}/status
Authorization: Bearer <token>
```

**Response:**
```json
{
  "session_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "in_progress",
  "current_step": "configuration",
  "progress_percentage": 66.6,
  "steps_completed": 2,
  "steps_total": 3,
  "estimated_time_remaining_minutes": 5,
  "current_operation": "Configuring IP pools...",
  "error_message": null,
  "can_cancel": true,
  "can_retry": false
}
```

#### Cancel Provisioning
```http
POST /api/v1/provisioning/sessions/{session_id}/cancel
Content-Type: application/json
Authorization: Bearer <token>

{
  "reason": "User requested cancellation",
  "force_cancel": false,
  "cleanup_partial_config": true
}
```

#### Get Provisioning Sessions
```http
GET /api/v1/provisioning/sessions?router_id=1&status=completed&page=1&size=10
Authorization: Bearer <token>
```

#### Get Provisioning Templates
```http
GET /api/v1/provisioning/templates?service_type=hotspot&is_active=true
Authorization: Bearer <token>
```

#### Get Default Configuration
```http
GET /api/v1/provisioning/default-configuration/hotspot
Authorization: Bearer <token>
```

**Response:**
```json
{
  "service_type": "hotspot",
  "configuration": {
    "hotspot_name": "ISP-Hotspot",
    "interface": "ether2",
    "ip_pool_start": "172.31.1.1",
    "ip_pool_end": "172.31.1.254",
    "gateway": "172.31.1.1",
    "dns_servers": ["8.8.8.8", "8.8.4.4"]
  }
}
```

#### Validate Configuration
```http
POST /api/v1/provisioning/validate-configuration?service_type=hotspot
Content-Type: application/json
Authorization: Bearer <token>

{
  "hotspot_name": "Test-Hotspot",
  "interface": "ether2"
}
```

#### Get Provisioning Statistics
```http
GET /api/v1/provisioning/stats?days=30
Authorization: Bearer <token>
```

**Response:**
```json
{
  "period_days": 30,
  "total_sessions": 45,
  "success_rate": 95.56,
  "average_duration_minutes": 18.5,
  "status_breakdown": {
    "completed": 43,
    "failed": 2,
    "cancelled": 0
  },
  "active_sessions": 0,
  "pending_sessions": 0
}
```

### Authentication Endpoints

#### Register User
```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "username": "johndoe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "password": "securepassword123",
  "role": "customer"
}
```

#### Login
```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=johndoe&password=securepassword123
```

#### Refresh Token
```http
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "your_refresh_token"
}
```

#### Logout
```http
POST /api/v1/auth/logout
Authorization: Bearer <access_token>
```

#### Get Current User
```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

#### Change Password
```http
POST /api/v1/auth/change-password
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "current_password": "oldpassword",
  "new_password": "newpassword123"
}
```

#### Forgot Password
```http
POST /api/v1/auth/forgot-password
Content-Type: application/json

{
  "email": "john@example.com"
}
```

### User Management Endpoints

#### Get Current User Profile
```http
GET /api/v1/users/me
Authorization: Bearer <access_token>
```

**Response:**
```json
{
  "id": 1,
  "username": "johndoe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "role": "customer",
  "status": "active",
  "subscription_count": 2,
  "active_subscription_count": 1,
  "total_invoices": 5,
  "pending_invoices": 1
}
```

#### Update Current User
```http
PATCH /api/v1/users/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "first_name": "John",
  "last_name": "Smith",
  "phone": "+254712345678"
}
```

#### Get All Users (Admin Only)
```http
GET /api/v1/users/?page=1&size=20&role=customer&status=active&search=john
Authorization: Bearer <admin_token>
```

**Query Parameters:**
- `page`: Page number (default: 1)
- `size`: Items per page (default: 20, max: 100)
- `role`: Filter by role (admin, technician, customer)
- `status`: Filter by status (active, inactive, suspended, pending_verification)
- `search`: Search in username, email, or name

#### Get User by ID (Admin/Technician)
```http
GET /api/v1/users/{user_id}
Authorization: Bearer <admin_or_technician_token>
```

#### Update User (Admin Only)
```http
PATCH /api/v1/users/{user_id}
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "first_name": "Updated",
  "last_name": "Name"
}
```

#### Update User Status (Admin Only)
```http
PATCH /api/v1/users/{user_id}/status?status=suspended
Authorization: Bearer <admin_token>
```

#### Update User Role (Admin Only)
```http
PATCH /api/v1/users/{user_id}/role?role=technician
Authorization: Bearer <admin_token>
```

#### Activate User (Admin Only)
```http
PATCH /api/v1/users/{user_id}/activate
Authorization: Bearer <admin_token>
```

#### Deactivate User (Admin Only)
```http
PATCH /api/v1/users/{user_id}/deactivate
Authorization: Bearer <admin_token>
```

#### Delete User (Admin Only)
```http
DELETE /api/v1/users/{user_id}
Authorization: Bearer <admin_token>
```

### Router Management Endpoints

#### Get All Routers (Technician/Admin)
```http
GET /api/v1/routers/
Authorization: Bearer <technician_or_admin_token>
```

#### Create Router (Technician/Admin)
```http
POST /api/v1/routers/
Authorization: Bearer <technician_or_admin_token>
Content-Type: application/json

{
  "name": "Main Router",
  "ip_address": "192.168.1.1",
  "username": "admin",
  "password": "router_password",
  "router_type": "mikrotik"
}
```

#### Get Router by ID (Technician/Admin)
```http
GET /api/v1/routers/{router_id}
Authorization: Bearer <technician_or_admin_token>
```

#### Update Router (Technician/Admin)
```http
PATCH /api/v1/routers/{router_id}
Authorization: Bearer <technician_or_admin_token>
Content-Type: application/json

{
  "name": "Updated Router Name",
  "description": "Updated description"
}
```

#### Delete Router (Technician/Admin)
```http
DELETE /api/v1/routers/{router_id}
Authorization: Bearer <technician_or_admin_token>
```

### Service Plans Endpoints

#### Get All Plans
```http
GET /api/v1/plans/
Authorization: Bearer <access_token>
```

#### Create Plan (Admin Only)
```http
POST /api/v1/plans/
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "name": "Basic Plan",
  "description": "Basic internet package",
  "plan_type": "hotspot",
  "price": 1000.00,
  "currency": "KES",
  "billing_cycle": "monthly",
  "download_speed": 10,
  "upload_speed": 5,
  "data_limit": 50,
  "validity_days": 30
}
```

#### Get Plan by ID
```http
GET /api/v1/plans/{plan_id}
Authorization: Bearer <access_token>
```

#### Update Plan (Admin Only)
```http
PATCH /api/v1/plans/{plan_id}
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "name": "Updated Plan Name",
  "price": 1200.00
}
```

#### Delete Plan (Admin Only)
```http
DELETE /api/v1/plans/{plan_id}
Authorization: Bearer <admin_token>
```

### Subscription Endpoints

#### Get All Subscriptions
```http
GET /api/v1/subscriptions/
Authorization: Bearer <access_token>
```

#### Create Subscription (Technician/Admin)
```http
POST /api/v1/subscriptions/
Authorization: Bearer <technician_or_admin_token>
Content-Type: application/json

{
  "user_id": 1,
  "plan_id": 1,
  "router_id": 1,
  "subscription_type": "hotspot",
  "username": "user123",
  "password": "password123",
  "start_date": "2024-01-01T00:00:00Z",
  "end_date": "2024-01-31T23:59:59Z"
}
```

#### Get Subscription by ID
```http
GET /api/v1/subscriptions/{subscription_id}
Authorization: Bearer <access_token>
```

#### Update Subscription (Technician/Admin)
```http
PATCH /api/v1/subscriptions/{subscription_id}
Authorization: Bearer <technician_or_admin_token>
Content-Type: application/json

{
  "status": "active",
  "notes": "Updated subscription"
}
```

#### Delete Subscription (Technician/Admin)
```http
DELETE /api/v1/subscriptions/{subscription_id}
Authorization: Bearer <technician_or_admin_token>
```

### Billing Endpoints

#### Get All Invoices
```http
GET /api/v1/billing/invoices/
Authorization: Bearer <access_token>
```

#### Generate Invoices (Admin Only)
```http
POST /api/v1/billing/invoices/generate
Authorization: Bearer <admin_token>
```

#### Get Invoice by ID
```http
GET /api/v1/billing/invoices/{invoice_id}
Authorization: Bearer <access_token>
```

#### Initiate MPESA STK Push
```http
POST /api/v1/billing/payments/mpesa/stk
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "phone_number": "+254712345678",
  "amount": 1000,
  "invoice_number": "INV-001"
}
```

#### MPESA Callback (Webhook)
```http
POST /api/v1/billing/payments/mpesa/callback
Content-Type: application/json

{
  "Body": {
    "stkCallback": {
      "MerchantRequestID": "29115-34620561-1",
      "CheckoutRequestID": "ws_CO_19122023102044012345",
      "ResultCode": 0,
      "ResultDesc": "The service request is processed successfully."
    }
  }
}
```

#### Get Payment History
```http
GET /api/v1/billing/payments/history
Authorization: Bearer <access_token>
```

### Notification Endpoints

#### Get Notifications
```http
GET /api/v1/notifications/
Authorization: Bearer <access_token>
```

#### Mark Notification as Read
```http
PATCH /api/v1/notifications/{notification_id}/read
Authorization: Bearer <access_token>
```

#### Send Email (Admin Only)
```http
POST /api/v1/notifications/email
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "user_id": 1,
  "subject": "Test Email",
  "message": "This is a test email"
}
```

#### Send SMS (Admin Only)
```http
POST /api/v1/notifications/sms
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "user_id": 1,
  "message": "This is a test SMS"
}
```

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Validation error message"
}
```

### 401 Unauthorized
```json
{
  "detail": "Could not validate credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Insufficient permissions"
}
```

### 404 Not Found
```json
{
  "detail": "Resource not found"
}
```

### 422 Unprocessable Entity
```json
{
  "detail": [
    {
      "loc": ["field_name"],
      "msg": "error message",
      "type": "error_type"
    }
  ]
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

## Rate Limiting

The API implements rate limiting to prevent abuse:

- **Default**: 100 requests per minute per IP
- **Authentication endpoints**: 10 requests per minute per IP
- **Payment endpoints**: 5 requests per minute per IP

Rate limit headers are included in responses:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1640995200
```

## Pagination

List endpoints support pagination:

**Query Parameters:**
- `page`: Page number (default: 1)
- `size`: Items per page (default: 20, max: 100)

**Response Format:**
```json
{
  "items": [...],
  "total": 150,
  "page": 1,
  "size": 20,
  "pages": 8
}
```

## Filtering and Searching

Many endpoints support filtering and searching:

**Common Filters:**
- `role`: Filter by user role
- `status`: Filter by status
- `search`: Search in relevant fields
- `created_at`: Filter by creation date
- `updated_at`: Filter by update date

**Example:**
```http
GET /api/v1/users/?role=customer&status=active&search=john&page=1&size=10
```

## Webhooks

### MPESA Payment Callback

The system accepts MPESA payment callbacks at:
```
POST /api/v1/billing/payments/mpesa/callback
```

**Callback Data Format:**
```json
{
  "Body": {
    "stkCallback": {
      "MerchantRequestID": "string",
      "CheckoutRequestID": "string",
      "ResultCode": 0,
      "ResultDesc": "string",
      "CallbackMetadata": {
        "Item": [
          {
            "Name": "Amount",
            "Value": 1000
          },
          {
            "Name": "MpesaReceiptNumber",
            "Value": "NEF61H8J60"
          }
        ]
      }
    }
  }
}
```

## SDKs and Examples

### Python Example
```python
import httpx

# Login
response = httpx.post(
    "http://localhost:8000/api/v1/auth/login",
    data={"username": "admin", "password": "admin123"}
)
token = response.json()["access_token"]

# Get current user
headers = {"Authorization": f"Bearer {token}"}
response = httpx.get(
    "http://localhost:8000/api/v1/users/me",
    headers=headers
)
print(response.json())
```

### JavaScript Example
```javascript
// Login
const loginResponse = await fetch('http://localhost:8000/api/v1/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
  },
  body: 'username=admin&password=admin123'
});
const { access_token } = await loginResponse.json();

// Get current user
const userResponse = await fetch('http://localhost:8000/api/v1/users/me', {
  headers: {
    'Authorization': `Bearer ${access_token}`
  }
});
const user = await userResponse.json();
console.log(user);
```

### cURL Examples

#### Login
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123"
```

#### Get Current User
```bash
curl -X GET "http://localhost:8000/api/v1/users/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### Create User
```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "username": "newuser",
    "email": "newuser@example.com",
    "first_name": "New",
    "last_name": "User",
    "password": "password123",
    "role": "customer"
  }'
```

## Support

For API support and questions:
- Check the interactive documentation at `/docs` (Swagger UI)
- Check the alternative documentation at `/redoc`
- Review the OpenAPI specification at `/openapi.json`
- Create an issue in the project repository

## Changelog

### Version 0.1.0
- Initial API release
- User authentication and management
- Basic billing endpoints
- Router management endpoints
- Service plan management
- Subscription management
- Notification system
- MPESA payment integration
