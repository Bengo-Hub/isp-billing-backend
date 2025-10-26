"""Authentication schemas for request/response models."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    """Token schema."""
    
    access_token: str
    token_type: str = "bearer"


class OAuth2Token(BaseModel):
    """OAuth2 token schema."""
    
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None


class TokenData(BaseModel):
    """Token data schema for JWT payload."""
    
    user_id: Optional[int] = None
    username: Optional[str] = None
    role: Optional[str] = None
    exp: Optional[datetime] = None


class LoginRequest(BaseModel):
    """Login request schema with default demo values for Swagger UI."""
    
    username: str = Field(
        default="demo",
        description="Username or email address",
        examples=["demo", "demo@codevertexitsolutions.com", "superuser"]
    )
    password: str = Field(
        default="demo123",
        description="User password",
        examples=["demo123", "superuser123"]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "username": "demo",
                "password": "demo123"
            }
        }


class TokenResponse(BaseModel):
    """Token response schema."""
    
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    
    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer"
            }
        }


class PermissionResponse(BaseModel):
    """Permission response schema."""
    
    id: int
    module: str
    action: str
    resource: Optional[str] = None
    description: Optional[str] = None


class LicenceResponse(BaseModel):
    """Licence response schema."""
    
    id: int
    licence_key: str
    organization_name: str
    licence_type: str
    trial_days: Optional[int] = None
    is_trial_active: bool = False
    days_remaining: int = 0


class UserResponse(BaseModel):
    """User response schema."""
    
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    company_name: Optional[str] = None
    phone: Optional[str] = None
    role: str
    status: str
    is_verified: bool
    is_active: bool
    avatar_url: Optional[str] = None
    permissions: List[PermissionResponse] = []
    licence: Optional[LicenceResponse] = None
    
    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Login response schema."""
    
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    
    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "user": {
                    "id": 1,
                    "username": "demo",
                    "email": "demo@codevertexitsolutions.com",
                    "first_name": "Demo",
                    "last_name": "Admin",
                    "company_name": "Demo ISP Company",
                    "role": "admin",
                    "status": "active",
                    "is_verified": True,
                    "is_active": True,
                    "permissions": [],
                    "licence": {
                        "licence_key": "DEMO-TRIAL-2024",
                        "licence_type": "trial",
                        "trial_days": 14,
                        "is_trial_active": True,
                        "days_remaining": 14
                    }
                }
            }
        }


class RegisterRequest(BaseModel):
    """Registration request schema."""
    
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique username",
        examples=["johndoe", "janedoe"]
    )
    email: EmailStr = Field(
        ...,
        description="Email address",
        examples=["john@ispcompany.com"]
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Password (minimum 8 characters)",
        examples=["SecurePass123!"]
    )
    first_name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="First name",
        examples=["John"]
    )
    last_name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Last name",
        examples=["Doe"]
    )
    phone: Optional[str] = Field(
        None,
        description="Phone number",
        examples=["+254700000000"]
    )
    company_name: Optional[str] = Field(
        None,
        max_length=200,
        description="Company/ISP name",
        examples=["ISP Company Ltd"]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "username": "johndoe",
                "email": "john@ispcompany.com",
                "password": "SecurePass123!",
                "first_name": "John",
                "last_name": "Doe",
                "phone": "+254700000000",
                "company_name": "ISP Company Ltd"
            }
        }


class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema."""
    
    email: EmailStr = Field(..., description="Email address")


class ResetPasswordRequest(BaseModel):
    """Reset password request schema."""
    
    token: str = Field(..., description="Reset token from email")
    new_password: str = Field(..., min_length=8, description="New password")


class ChangePasswordRequest(BaseModel):
    """Change password request schema."""
    
    old_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")


class VerifyEmailRequest(BaseModel):
    """Email verification request schema."""
    
    token: str = Field(..., description="Verification token from email")


class RefreshTokenRequest(BaseModel):
    """Refresh token request schema."""
    
    refresh_token: str = Field(..., description="Refresh token")
