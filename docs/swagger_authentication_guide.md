# Swagger UI Authentication Guide

## 🔧 Fixed Issues

### Previous Problems
1. **Token not automatically appended**: After login in Swagger UI, the JWT token wasn't being automatically included in subsequent request headers
2. **Poor OAuth2 integration**: The authentication flow wasn't properly configured for Swagger UI's OAuth2 password flow
3. **Missing security schemes**: Only basic Bearer auth was configured, lacking OAuth2 compatibility
4. **Unclear documentation**: No clear instructions for users on how to authenticate in Swagger UI

### ✅ Solutions Implemented

## 🚀 Enhanced Swagger Configuration

### 1. Dual Security Schemes
Added both Bearer Token and OAuth2 Password Flow support:

```python
"securitySchemes": {
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer", 
        "bearerFormat": "JWT",
        "description": "Enter your JWT token (without 'Bearer ' prefix)"
    },
    "OAuth2PasswordBearer": {
        "type": "oauth2",
        "flows": {
            "password": {
                "tokenUrl": "/api/v1/auth/login",
                "scopes": {
                    "read": "Read access",
                    "write": "Write access", 
                    "admin": "Admin access"
                }
            }
        }
    }
}
```

### 2. Automatic Security Application
All protected endpoints now automatically include both security schemes:

```python
endpoint["security"] = [
    {"BearerAuth": []},
    {"OAuth2PasswordBearer": ["read", "write"]}
]
```

### 3. Enhanced Login Endpoint
Improved the `/api/v1/auth/login` endpoint with:
- Better documentation and examples
- OAuth2 password flow compatibility
- Clear instructions for Swagger UI usage
- Default test credentials

## 🔐 How to Use Swagger Authentication

### Method 1: OAuth2 Password Flow (Recommended)

1. **Open Swagger UI**: Navigate to `http://localhost:8000/docs`

2. **Click "Authorize"**: Look for the lock icon 🔒 at the top right

3. **Choose OAuth2PasswordBearer**: In the authorization modal

4. **Enter Credentials**:
   - **Username**: `admin`
   - **Password**: `admin123`
   - **Client ID**: (leave empty)
   - **Client Secret**: (leave empty)

5. **Click "Authorize"**: The token will be automatically obtained and stored

6. **Test Protected Endpoints**: All subsequent API calls will include the JWT token automatically

### Method 2: Manual Bearer Token

1. **Login via API**: Use the `/api/v1/auth/login` endpoint to get a token

2. **Copy Access Token**: From the response, copy the `access_token` value

3. **Click "Authorize"**: Choose the "BearerAuth" option

4. **Enter Token**: Paste the token (without "Bearer " prefix)

5. **Click "Authorize"**: The token will be included in all requests

## 👥 Default Test Accounts

### Admin Account
- **Username**: `admin`
- **Password**: `admin123`
- **Role**: Admin (full access)
- **Email**: `admin@ispbilling.com`

### Technician Accounts
- **Username**: `tech1` | **Password**: `tech123`
- **Username**: `tech2` | **Password**: `tech123`  
- **Username**: `support` | **Password**: `tech123`
- **Role**: Technician (device and customer management)

### Customer Account (Sample)
- **Username**: Any customer username from seeded data
- **Password**: `customer123`
- **Role**: Customer (limited access)

## 🔍 Verification Steps

### 1. Check Authentication Status
After authorization, you should see:
- 🔒 Lock icon shows as "locked"
- Green checkmark next to security schemes
- "Logout" button appears in the authorization modal

### 2. Test Protected Endpoint
Try any protected endpoint (e.g., `/api/v1/users/me`):
- Should return user data without 401 errors
- Request headers should include `Authorization: Bearer <token>`

### 3. Check Token in Browser DevTools
In the Network tab, verify requests include:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## 🛠️ Technical Implementation Details

### Enhanced OpenAPI Schema
```python
def custom_openapi():
    """Custom OpenAPI schema with JWT security and OAuth2 password flow."""
    # ... comprehensive security configuration
    
    # Add both security schemes for flexibility
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": { /* Bearer token config */ },
        "OAuth2PasswordBearer": { /* OAuth2 config */ }
    }
    
    # Apply security to all protected endpoints
    for path in openapi_schema["paths"]:
        # ... security application logic
```

### OAuth2-Compatible Token Response
```python
class Token(BaseModel):
    """Schema for authentication tokens - OAuth2 compatible."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 1800
            }
        }
    }
```

### Public Endpoints Configuration
These endpoints don't require authentication:
```python
public_paths = {
    "/", "/health", "/docs", "/redoc", "/openapi.json",
    "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh",
    "/api/v1/auth/verify", "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password",
    "/api/v1/auth/verify-email", "/api/v1/auth/verify-phone"
}
```

## 🎯 Benefits of the Fix

### For Developers
- **Seamless Testing**: No need to manually copy/paste tokens
- **Better DX**: Clear authentication flow in Swagger UI
- **Multiple Options**: Both OAuth2 and Bearer token methods available
- **Auto-Refresh**: Tokens are automatically managed

### For API Users
- **Standard OAuth2**: Familiar authentication flow
- **Clear Documentation**: Step-by-step instructions in Swagger
- **Test Credentials**: Ready-to-use demo accounts
- **Error Handling**: Clear error messages for auth failures

### For Production
- **Security**: Proper JWT token validation
- **Scalability**: OAuth2 standard compliance
- **Flexibility**: Multiple authentication methods
- **Monitoring**: Better auth event tracking

## 🚨 Security Considerations

### Development Environment
- Default credentials are for testing only
- Change default passwords in production
- Use environment variables for secrets

### Production Environment
- Implement proper user management
- Use strong passwords and 2FA
- Configure HTTPS only
- Implement rate limiting on auth endpoints

## 🔧 Troubleshooting

### Token Not Working
1. Check token expiration (30 minutes default)
2. Verify correct endpoint usage
3. Ensure token includes proper claims
4. Check for typos in manual entry

### Authorization Button Missing
1. Verify FastAPI app includes security schemes
2. Check OpenAPI schema generation
3. Ensure endpoints have security requirements

### 401 Unauthorized Errors
1. Verify token is valid and not expired
2. Check user account is active
3. Ensure proper role permissions
4. Verify token format (no extra spaces)

## 📚 Additional Resources

- [FastAPI Security Documentation](https://fastapi.tiangolo.com/tutorial/security/)
- [OAuth2 Password Flow Specification](https://tools.ietf.org/html/rfc6749#section-4.3)
- [JWT Token Standard](https://tools.ietf.org/html/rfc7519)
- [Swagger UI Authentication](https://swagger.io/docs/specification/authentication/)

## 🎉 Success!

With these improvements, the Swagger UI now provides:
- ✅ Automatic token management
- ✅ OAuth2 password flow integration
- ✅ Clear authentication instructions
- ✅ Multiple authentication methods
- ✅ Production-ready security configuration

Users can now seamlessly authenticate in Swagger UI and have their JWT tokens automatically included in all subsequent API requests!
