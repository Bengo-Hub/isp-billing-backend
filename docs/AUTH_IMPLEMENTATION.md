# Authentication Implementation - Backend

## Overview
This document details the backend authentication implementation, including support for both email and username login.

---

## Login Endpoint Support

### Flexible Login: Email OR Username

The backend authentication should support login with either:
1. **Username**: `demo`
2. **Email**: `demo@codevertexitsolutions.com`

Both should work for the same account.

---

## Implementation

### Auth Service (`app/services/auth_service.py`)

```python
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.user import User
from app.core.security import verify_password, create_access_token

class AuthService:
    def __init__(self, db: Session):
        self.db = db
    
    def authenticate_user(self, username_or_email: str, password: str) -> User | None:
        """
        Authenticate user by username OR email.
        
        Args:
            username_or_email: Can be either username or email
            password: Plain text password
        
        Returns:
            User object if authentication successful, None otherwise
        """
        # Query user by username OR email
        user = self.db.query(User).filter(
            or_(
                User.username == username_or_email,
                User.email == username_or_email
            )
        ).first()
        
        if not user:
            return None
        
        # Verify password
        if not verify_password(password, user.hashed_password):
            return None
        
        # Check if user is active
        if not user.is_active:
            return None
        
        return user
    
    def login(self, username_or_email: str, password: str) -> dict:
        """
        Login user and return access token.
        
        Returns:
            {
                "access_token": "jwt_token",
                "token_type": "bearer",
                "user": {...user data...}
            }
        """
        # Authenticate user
        user = self.authenticate_user(username_or_email, password)
        
        if not user:
            raise AuthenticationError("Invalid credentials")
        
        # Update last login
        user.last_login = datetime.utcnow()
        self.db.commit()
        
        # Create access token
        access_token = create_access_token(
            data={"sub": str(user.id), "role": user.role.value}
        )
        
        # Get user permissions and licence
        from app.modules.auth import RBACService
        rbac_service = RBACService(self.db)
        
        permissions = rbac_service.get_user_permissions(user.id)
        licence = rbac_service.get_user_licence(user.id)
        
        # Prepare user data
        user_data = user.to_dict()
        user_data['permissions'] = [
            {
                'id': p.id,
                'module': p.module.value,
                'action': p.action.value,
                'resource': p.resource,
                'description': p.description
            }
            for p in permissions
        ]
        
        if licence:
            user_data['licence'] = {
                'id': licence.id,
                'licence_key': licence.licence_key,
                'organization_name': licence.organization_name,
                'licence_type': licence.licence_type,
                'trial_days': licence.trial_days,
                'is_trial_active': licence.is_trial_active,
                'days_remaining': licence.days_remaining
            }
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": user_data
        }
```

### Auth Endpoint (`app/api/v1/auth.py`)

```python
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.modules.auth import AuthService
from app.schemas.auth import LoginResponse, TokenResponse

router = APIRouter()

@router.post("/login", response_model=LoginResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login with username or email.
    
    Accepts:
    - username: Can be actual username OR email address
    - password: User's password
    
    Returns:
    - access_token: JWT token
    - token_type: "bearer"
    - user: Complete user object with permissions and licence
    """
    auth_service = AuthService(db)
    
    try:
        result = auth_service.login(
            username_or_email=form_data.username,  # Can be username OR email
            password=form_data.password
        )
        return result
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.post("/register", response_model=LoginResponse)
async def register(
    data: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Register a new user.
    
    Required fields:
    - username: Unique username
    - email: Unique email address
    - password: Minimum 8 characters
    - first_name: User's first name
    - last_name: User's last name
    
    Optional fields:
    - phone: Phone number
    - company_name: Company/ISP name
    """
    auth_service = AuthService(db)
    
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(
            or_(
                User.username == data.username,
                User.email == data.email
            )
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email already registered"
            )
        
        # Create user
        user = auth_service.create_user(data)
        
        # Auto-login after registration
        result = auth_service.login(
            username_or_email=user.username,
            password=data.password  # Plain text password, before hashing
        )
        
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
```

---

## Schema Definitions

### Login Request

```python
# Using OAuth2PasswordRequestForm (built-in FastAPI)
class OAuth2PasswordRequestForm:
    username: str  # Can accept username OR email
    password: str
    scope: str = ""
    client_id: str | None = None
    client_secret: str | None = None
```

**Swagger UI Example**:
```json
{
  "username": "demo",  // or "demo@codevertexitsolutions.com"
  "password": "demo123"
}
```

### Registration Request

```python
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, example="johndoe")
    email: EmailStr = Field(..., example="john@ispcompany.com")
    password: str = Field(..., min_length=8, example="SecurePass123!")
    first_name: str = Field(..., min_length=1, max_length=50, example="John")
    last_name: str = Field(..., min_length=1, max_length=50, example="Doe")
    phone: str | None = Field(None, example="+254700000000")
    company_name: str | None = Field(None, max_length=200, example="ISP Company Ltd")
```

### Login Response

```python
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    
class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    company_name: str | None
    phone: str | None
    role: str
    status: str
    is_verified: bool
    is_active: bool
    avatar_url: str | None
    permissions: List[PermissionResponse] = []
    licence: LicenceResponse | None = None
```

---

## Database Query for Flexible Login

### SQL Query Generated

```sql
SELECT * FROM users 
WHERE username = 'demo' OR email = 'demo@codevertexitsolutions.com'
LIMIT 1;
```

This allows both:
- `username='demo'` AND `password='demo123'`
- `username='demo@codevertexitsolutions.com'` AND `password='demo123'`

To authenticate the same account.

---

## Security Considerations

### Password Hashing
```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    """Hash password using bcrypt."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)
```

### JWT Token Generation
```python
from jose import jwt
from datetime import datetime, timedelta

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    """Create JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=30)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode, 
        SECRET_KEY, 
        algorithm=ALGORITHM
    )
    
    return encoded_jwt
```

---

## Testing

### Test Login with Username
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=demo&password=demo123"
```

### Test Login with Email
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=demo@codevertexitsolutions.com&password=demo123"
```

Both should return the same response:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "demo",
    "email": "demo@codevertexitsolutions.com",
    ...
  }
}
```

---

## Frontend Integration

### Login Form Submission

The frontend sends either username or email in the `username` field:

```typescript
// lib/store/auth.ts
login: async (email: string, password: string) => {
  const response = await api.post('/auth/login', { 
    username: email,  // Backend accepts both username AND email
    password 
  });
  
  const { access_token, user } = response.data;
  // ... store token and user
}
```

### Using Username Directly

If the frontend wants to support username input:

```typescript
// Alternative: Accept username OR email
login: async (usernameOrEmail: string, password: string) => {
  const response = await api.post('/auth/login', { 
    username: usernameOrEmail,  // Can be username OR email
    password 
  });
}
```

---

## Error Handling

### Invalid Credentials
```json
{
  "detail": "Invalid credentials",
  "status_code": 401
}
```

### Inactive Account
```json
{
  "detail": "Account is inactive",
  "status_code": 403
}
```

### User Not Found
```json
{
  "detail": "Invalid credentials",  // Don't reveal if user exists
  "status_code": 401
}
```

---

**Last Updated**: October 21, 2025  
**Version**: 1.0.0  
**Author**: Codevertex IT Solutions

