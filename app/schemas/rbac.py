"""RBAC schemas for request/response models."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class RoleBase(BaseModel):
    """Base role schema."""
    name: str
    description: Optional[str] = None
    is_system_role: bool = False


class RoleCreate(RoleBase):
    """Role creation schema."""
    pass


class RoleUpdate(BaseModel):
    """Role update schema."""
    name: Optional[str] = None
    description: Optional[str] = None
    is_system_role: Optional[bool] = None


class PermissionResponse(BaseModel):
    """Permission response schema."""
    id: int
    module: str
    action: str
    resource: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoleResponse(RoleBase):
    """Role response schema."""
    id: int
    created_at: datetime
    updated_at: datetime
    permissions: List[PermissionResponse] = []

    class Config:
        from_attributes = True


class UserPermissionCreate(BaseModel):
    """User permission override creation schema."""
    user_id: int
    permission_id: int
    is_granted: bool
    reason: Optional[str] = None
    expires_at: Optional[datetime] = None


class UserPermissionResponse(BaseModel):
    """User permission override response schema."""
    id: int
    user_id: int
    permission_id: int
    is_granted: bool
    reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    permission: PermissionResponse

    class Config:
        from_attributes = True


class SystemLicenceBase(BaseModel):
    """Base licence schema."""
    licence_key: str
    organization_name: str
    contact_email: str
    contact_phone: Optional[str] = None
    licence_type: str = "trial"
    is_active: bool = True
    max_users: int = 10
    max_routers: int = 5
    trial_days: int = 14
    auto_renew: bool = False


class LicenceCreate(SystemLicenceBase):
    """Licence creation schema."""
    pass


class LicenceUpdate(BaseModel):
    """Licence update schema."""
    licence_key: Optional[str] = None
    organization_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    licence_type: Optional[str] = None
    is_active: Optional[bool] = None
    max_users: Optional[int] = None
    max_routers: Optional[int] = None
    trial_days: Optional[int] = None
    auto_renew: Optional[bool] = None


class LicenceResponse(SystemLicenceBase):
    """Licence response schema."""
    id: int
    trial_started_at: Optional[datetime] = None
    trial_expires_at: Optional[datetime] = None
    subscription_started_at: Optional[datetime] = None
    subscription_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    is_trial_active: bool
    days_remaining: int

    class Config:
        from_attributes = True
