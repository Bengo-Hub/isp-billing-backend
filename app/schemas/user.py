"""User-related Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, validator, computed_field

from app.models.user import UserRole, UserStatus


class UserBase(BaseModel):
    """Base user schema."""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    role: UserRole = UserRole.CUSTOMER
    bio: Optional[str] = None

    @validator("phone")
    def validate_phone(cls, v):
        """Validate phone number format."""
        if v and not v.startswith("+"):
            # Add country code if not present (assuming Kenya +254)
            v = f"+254{v.lstrip('0')}"
        return v


class UserCreate(UserBase):
    """Schema for creating a user."""

    password: str = Field(..., min_length=8, max_length=100)


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, min_length=1, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)
    bio: Optional[str] = None
    avatar_url: Optional[str] = None

    @validator("phone")
    def validate_phone(cls, v):
        """Validate phone number format."""
        if v and not v.startswith("+"):
            v = f"+254{v.lstrip('0')}"
        return v


class UserInDB(UserBase):
    """Schema for user in database."""

    id: int
    is_verified: bool
    is_active: bool
    status: UserStatus
    avatar_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    email_verified_at: Optional[datetime] = None
    phone_verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class User(UserInDB):
    """Schema for user response."""

    @computed_field
    @property
    def full_name(self) -> str:
        """Get user's full name."""
        return f"{self.first_name} {self.last_name}"


class UserResponse(User):
    """Schema for user response (alias for User)."""
    pass


class UserProfile(User):
    """Schema for user profile with additional details."""

    subscription_count: int = 0
    active_subscription_count: int = 0
    total_invoices: int = 0
    pending_invoices: int = 0


class UserLogin(BaseModel):
    """Schema for user login."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=1)


class UserPasswordChange(BaseModel):
    """Schema for password change."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)


class AdminSetPassword(BaseModel):
    """Schema for admin setting a user's password."""

    new_password: str = Field(..., min_length=8, max_length=100)


class UserPasswordReset(BaseModel):
    """Schema for password reset request."""

    email: EmailStr


class UserPasswordResetConfirm(BaseModel):
    """Schema for password reset confirmation."""

    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)


class UserVerification(BaseModel):
    """Schema for user verification."""

    token: str = Field(..., min_length=1)
    verification_type: str = Field(..., pattern="^(email|phone)$")


class Token(BaseModel):
    """Schema for authentication tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRefresh(BaseModel):
    """Schema for token refresh."""

    refresh_token: str = Field(..., min_length=1)


class UserSession(BaseModel):
    """Schema for user session."""

    id: int
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_activity: datetime
    expires_at: datetime

    class Config:
        from_attributes = True
