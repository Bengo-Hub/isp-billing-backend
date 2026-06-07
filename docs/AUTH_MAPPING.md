# Authentication API Mapping - Frontend to Backend

## Overview
This document explains how the frontend authentication forms map to the backend API endpoints and database models.

---

## Backend User Model

### User Table Schema
```python
class User(Base):
    __tablename__ = "users"
    
    # Primary key
    id: Integer
    
    # Basic information (REQUIRED)
    username: String(50)  # Unique, indexed
    email: String(100)     # Unique, indexed
    first_name: String(50) # Required
    last_name: String(50)  # Required
    
    # Optional fields
    phone: String(20)      # Unique, indexed, nullable
    company_name: String(200)  # Nullable (for ISP providers)
    
    # Authentication
    hashed_password: String(255)
    is_verified: Boolean (default=False)
    is_active: Boolean (default=True)
    
    # RBAC
    role: Enum (superuser, admin, technician, customer)
    status: Enum (active, inactive, suspended, pending_verification)
    role_id: Integer (FK to roles.id)
    
    # Profile
    avatar_url: String(500)
    bio: Text
    last_login: DateTime
    
    # Timestamps
    created_at: DateTime
    updated_at: DateTime
    email_verified_at: DateTime
    phone_verified_at: DateTime
```

---

## Login Flow

### Frontend Form (Login Page)

**File**: `wifi-billing-software-frontend/app/(marketing)/login/page.tsx`

**Form Fields**:
```typescript
{
  email: string      // User enters email or username
  password: string   // User's password
  remember: boolean  // Remember me checkbox
}
```

**Default Values** (for demo):
```typescript
{
  email: 'demo@codevertexitsolutions.com',
  password: 'demo123',
  remember: false
}
```

### Frontend Auth Store

**File**: `wifi-billing-software-frontend/lib/store/auth.ts`

**Login Function**:
```typescript
login: async (email: string, password: string) => {
  // IMPORTANT: Backend expects form data (OAuth2PasswordRequestForm)
  // NOT JSON! Must use application/x-www-form-urlencoded
  const formData = new URLSearchParams();
  formData.append('username', email);  // Backend accepts email as username
  formData.append('password', password);
  
  const response = await api.post('/auth/login', formData, {
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    }
  });
  
  // Response structure
  const { access_token, user } = response.data;
}
```

**Mapping**:
- Frontend `email` → Backend `username`
- Frontend `password` → Backend `password`

### Backend API Endpoint

**Endpoint**: `POST /api/v1/auth/login`

**Content-Type**: `application/x-www-form-urlencoded` (OAuth2 standard)

**Request Body** (Form Data):
```
username=demo&password=demo123
```
OR
```
username=demo@codevertexitsolutions.com&password=demo123
```

**Note**: The backend uses OAuth2PasswordRequestForm which requires form-encoded data, NOT JSON!

**Response**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "demo",
    "email": "demo@codevertexitsolutions.com",
    "first_name": "Demo",
    "last_name": "User",
    "company_name": "Demo ISP Company",
    "role": "admin",
    "status": "active",
    "is_verified": true,
    "is_active": true,
    "permissions": [...],
    "licence": {...}
  }
}
```

---

## Registration Flow

### Frontend Form (Signup Page)

**File**: `wifi-billing-software-frontend/app/(marketing)/signup/page.tsx`

**Multi-Step Form Fields**:

**Step 1: Business Email**
```typescript
{
  business_email: string  // ISP provider's email
}
```

**Step 2: Business Details**
```typescript
{
  full_name: string      // User's full name
  company_name: string   // ISP company name
  phone_number: string   // Contact phone
}
```

**Step 3: Password**
```typescript
{
  password: string          // Chosen password
  confirmPassword: string   // Password confirmation
  agreeToTerms: boolean     // T&C agreement
}
```

### Frontend Data Transformation

**Before Sending to Backend**:
```typescript
// Parse full name
const nameParts = formData.full_name.trim().split(' ');
const firstName = nameParts[0] || formData.full_name;
const lastName = nameParts.slice(1).join(' ') || nameParts[0];

// Prepare registration data
const registrationData = {
  username: formData.business_email.split('@')[0],  // Extract username from email
  email: formData.business_email,
  password: formData.password,
  first_name: firstName,
  last_name: lastName,
  phone: formData.phone_number,
  company_name: formData.company_name,
};
```

### Frontend Auth Store

**File**: `wifi-billing-software-frontend/lib/store/auth.ts`

**Register Function**:
```typescript
interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  phone?: string;
  company_name?: string;
}

register: async (data: RegisterRequest) => {
  const response = await api.makeRequest('/auth/register', {
    method: 'POST',
    data: data
  });
  
  const { access_token, user } = response;
}
```

### Backend API Endpoint

**Endpoint**: `POST /api/v1/auth/register`

**Request Body**:
```json
{
  "username": "john",
  "email": "john@ispcompany.com",
  "password": "SecurePass123!",
  "first_name": "John",
  "last_name": "Doe",
  "phone": "+254700000000",
  "company_name": "ISP Company Ltd"
}
```

**Response**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": 2,
    "username": "john",
    "email": "john@ispcompany.com",
    "first_name": "John",
    "last_name": "Doe",
    "phone": "+254700000000",
    "company_name": "ISP Company Ltd",
    "role": "admin",
    "status": "pending_verification",
    "is_verified": false,
    "is_active": true,
    "permissions": [...],
    "licence": {
      "licence_key": "TRIAL-...",
      "licence_type": "trial",
      "trial_days": 14,
      "is_trial_active": true,
      "days_remaining": 14
    }
  }
}
```

---

## Field Mapping Summary

### Login
| Frontend Field | Backend Field | Type | Required | Notes |
|---------------|---------------|------|----------|-------|
| email | username | string | Yes | Backend accepts email OR username |
| password | password | string | Yes | Plain text, hashed by backend |

### Registration
| Frontend Field | Backend Field | Type | Required | Notes |
|---------------|---------------|------|----------|-------|
| business_email | email | string | Yes | Must be valid email |
| business_email (parsed) | username | string | Yes | Extracted from email (before @) |
| full_name (parsed) | first_name | string | Yes | First word of full name |
| full_name (parsed) | last_name | string | Yes | Remaining words |
| phone_number | phone | string | No | Optional phone number |
| company_name | company_name | string | No | ISP company name |
| password | password | string | Yes | Minimum 8 characters |

---

## Demo Accounts

### Demo Admin Account
```json
{
  "username": "demo",
  "password": "demo123",
  "email": "demo@codevertexitsolutions.com",
  "first_name": "Demo",
  "last_name": "Admin",
  "company_name": "Demo ISP Company",
  "role": "admin",
  "licence_key": "DEMO-TRIAL-2024"
}
```

**Usage**: For ISP provider testing
**Permissions**: Full admin access (not superuser)
**Licence**: 14-day trial

### Superuser Account
```json
{
  "username": "superuser",
  "password": "superuser123",
  "email": "superuser@codevertexitsolutions.com",
  "first_name": "Super",
  "last_name": "User",
  "role": "superuser"
}
```

**Usage**: For system configuration and advanced settings
**Permissions**: Full system access
**Licence**: N/A (superuser doesn't need licence)

---

## Swagger UI Integration

### Default Credentials Display

**Location**: `http://localhost:8000/docs`

**OAuth2 Authorization**:
```
OAuth2 password flow - **Demo Credentials:**

**Demo Admin:** `demo` / `demo123`

**Superuser:** `superuser` / `superuser123`
```

**How to Use in Swagger**:
1. Click "Authorize" button
2. Enter username: `demo`
3. Enter password: `demo123`
4. Click "Authorize"
5. All authenticated endpoints are now accessible

---

## Frontend Login Form Defaults

The login form is pre-filled with demo credentials for easy testing:

```typescript
const [formData, setFormData] = useState({
  email: 'demo@codevertexitsolutions.com',  // Default demo email
  password: 'demo123',  // Default demo password
  remember: false,
});
```

**Benefits**:
- Immediate testing without typing
- Clear demonstration of working credentials
- Easy for developers and testers
- Production deployment should remove defaults

---

## Authentication Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                        │
│                                                              │
│  Login Form                                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Email:    demo@codevertexitsolutions.com             │  │
│  │ Password: ••••••••                                    │  │
│  │ [x] Remember me                                       │  │
│  │                                                        │  │
│  │ [ Login Button ]                                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  Auth Store (Zustand)                                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ login(email, password)                                │  │
│  │   ↓                                                    │  │
│  │ API Request: POST /auth/login                         │  │
│  │ {                                                      │  │
│  │   username: email,  // Converted                      │  │
│  │   password: password                                   │  │
│  │ }                                                      │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                          │
│                                                              │
│  POST /api/v1/auth/login                                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1. Validate credentials                                │  │
│  │ 2. Check user exists (by username OR email)           │  │
│  │ 3. Verify password hash                               │  │
│  │ 4. Generate JWT token                                 │  │
│  │ 5. Load user permissions                              │  │
│  │ 6. Load licence information                           │  │
│  │ 7. Return token + user data                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  Response                                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ {                                                      │  │
│  │   access_token: "eyJ...",                             │  │
│  │   token_type: "bearer",                               │  │
│  │   user: { ...user data... }                           │  │
│  │ }                                                      │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                        │
│                                                              │
│  Auth Store Update                                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1. Save token to state                                │  │
│  │ 2. Save user to state                                 │  │
│  │ 3. Set isAuthenticated = true                         │  │
│  │ 4. Update RBAC store with permissions                 │  │
│  │ 5. Persist to localStorage                            │  │
│  │ 6. Redirect to /dashboard                             │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Validation Rules

### Frontend Validation (Login)
```typescript
- email: Required, must be valid email format
- password: Required
```

### Frontend Validation (Signup)
```typescript
- business_email: Required, valid email format
- full_name: Required
- company_name: Required
- phone_number: Required, valid phone format
- password: Required, minimum 8 characters
- confirmPassword: Must match password
- agreeToTerms: Must be true
```

### Backend Validation
```python
- username: Required, 3-50 characters, unique
- email: Required, valid email format, unique
- first_name: Required, 1-50 characters
- last_name: Required, 1-50 characters
- phone: Optional, valid phone format, unique if provided
- password: Required, minimum 8 characters
- company_name: Optional, max 200 characters
```

---

## Security Considerations

### Password Security
- Frontend sends plain text password over HTTPS
- Backend hashes password using bcrypt
- Hashed password stored in database
- Never store or return plain text passwords

### Token Security
- JWT tokens expire after 30 minutes (configurable)
- Refresh tokens valid for 7 days
- Tokens stored in localStorage (consider httpOnly cookies for production)
- Token includes user ID, role, and permissions claims

### RBAC Integration
- User role assigned on registration (default: "customer" or "admin" for ISPs)
- Permissions loaded on login
- Frontend UI gated by permissions
- Backend endpoints protected by permission decorators

---

## Testing

### Manual Testing

**Test Login** (with form data):
```bash
# Using username
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=demo&password=demo123"

# Using email
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=demo@codevertexitsolutions.com&password=demo123"
```

**Test Registration**:
```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "TestPass123!",
    "first_name": "Test",
    "last_name": "User",
    "phone": "+254700000001",
    "company_name": "Test ISP"
  }'
```

### Automated Testing
```typescript
// Frontend test
describe('Auth Store', () => {
  it('should login with valid credentials', async () => {
    const { login } = useAuthStore.getState()
    await login('demo@codevertexitsolutions.com', 'demo123')
    
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    expect(useAuthStore.getState().user).not.toBeNull()
  })
})
```

---

## Troubleshooting

### Common Issues

#### 1. "Invalid credentials" error
**Cause**: Mismatch between frontend field names and backend expectations
**Solution**: Ensure frontend sends `username` not `email` to login endpoint

#### 2. "Field required" error on registration
**Cause**: Missing required fields (first_name, last_name)
**Solution**: Parse full_name into first_name and last_name before sending

#### 3. "User already exists" error
**Cause**: Email or username already registered
**Solution**: Use unique email addresses for each account

#### 4. Token not persisting
**Cause**: localStorage not saving token
**Solution**: Check browser permissions and Zustand persist configuration

---

**Last Updated**: October 21, 2025  
**Version**: 1.0.0  
**Author**: Codevertex Africa Limited

