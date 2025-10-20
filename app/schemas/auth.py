"""Authentication-related Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, validator

from app.models.user import UserRole
from app.core.security import TokenData


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


class OAuth2Token(BaseModel):
    """OAuth2 compatible token response for Swagger UI."""
    
    access_token: str = Field(..., description="The access token")
    token_type: str = Field(default="bearer", description="The token type")
    expires_in: Optional[int] = Field(default=1800, description="Token expiration time in seconds")
    refresh_token: Optional[str] = Field(None, description="The refresh token")
    scope: Optional[str] = Field(None, description="The scope of the access token")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 1800,
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "scope": "read write"
            }
        }
    }


class LoginRequest(BaseModel):
    """Schema for login request."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    """Schema for registration request."""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)
    role: UserRole = UserRole.CUSTOMER

    @validator("phone")
    def validate_phone(cls, v):
        """Validate phone number format."""
        if v and not v.startswith("+"):
            v = f"+254{v.lstrip('0')}"
        return v


class PasswordResetRequest(BaseModel):
    """Schema for password reset request."""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Schema for password reset confirmation."""

    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)


class ChangePasswordRequest(BaseModel):
    """Schema for password change request."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)


class RefreshTokenRequest(BaseModel):
    """Schema for token refresh request."""

    refresh_token: str = Field(..., min_length=1)


class EmailVerificationRequest(BaseModel):
    """Schema for email verification request."""

    token: str = Field(..., min_length=1)


class PhoneVerificationRequest(BaseModel):
    """Schema for phone verification request."""

    token: str = Field(..., min_length=1)


class TwoFactorSetupRequest(BaseModel):
    """Schema for 2FA setup request."""

    password: str = Field(..., min_length=1)


class TwoFactorVerifyRequest(BaseModel):
    """Schema for 2FA verification request."""

    code: str = Field(..., min_length=6, max_length=6)


class SessionInfo(BaseModel):
    """Schema for session information."""

    session_id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    last_activity: datetime
    expires_at: datetime
    is_active: bool
