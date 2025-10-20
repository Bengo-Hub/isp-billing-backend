"""Router-related Pydantic schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.router import RouterStatus, RouterType


class RouterDeviceBase(BaseModel):
    """Base router device schema."""

    name: str = Field(..., min_length=1, max_length=100)
    device_type: Optional[str] = Field(None, max_length=50)
    mac_address: Optional[str] = Field(None, max_length=17)
    ip_address: Optional[str] = Field(None, max_length=45)
    status: str = Field("active", max_length=20)
    description: Optional[str] = None

    @validator("mac_address")
    def validate_mac_address(cls, v):
        """Validate MAC address format."""
        if v:
            import re
            mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
            if not re.match(mac_pattern, v):
                raise ValueError("Invalid MAC address format")
        return v

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        if v:
            import re
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, v):
                raise ValueError("Invalid IP address format")
        return v


class RouterDeviceCreate(RouterDeviceBase):
    """Schema for creating a router device."""
    pass


class RouterDeviceUpdate(BaseModel):
    """Schema for updating a router device."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    device_type: Optional[str] = Field(None, max_length=50)
    mac_address: Optional[str] = Field(None, max_length=17)
    ip_address: Optional[str] = Field(None, max_length=45)
    status: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = None

    @validator("mac_address")
    def validate_mac_address(cls, v):
        """Validate MAC address format."""
        if v:
            import re
            mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
            if not re.match(mac_pattern, v):
                raise ValueError("Invalid MAC address format")
        return v

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        if v:
            import re
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, v):
                raise ValueError("Invalid IP address format")
        return v


class RouterDevice(RouterDeviceBase):
    """Schema for router device response."""

    id: int
    router_id: int
    last_seen: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RouterBase(BaseModel):
    """Base router schema."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    router_type: RouterType = RouterType.MIKROTIK
    ip_address: str = Field(..., min_length=7, max_length=45)
    port: int = Field(8728, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=255)
    location: Optional[str] = Field(None, max_length=200)
    latitude: Optional[str] = Field(None, max_length=20)
    longitude: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        import re
        ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        if not re.match(ip_pattern, v):
            raise ValueError("Invalid IP address format")
        return v



class RouterCreate(RouterBase):
    """Schema for creating a router."""
    pass


class RouterUpdate(BaseModel):
    """Schema for updating a router."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    ip_address: Optional[str] = Field(None, min_length=7, max_length=45)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = Field(None, min_length=1, max_length=50)
    password: Optional[str] = Field(None, min_length=1, max_length=255)
    location: Optional[str] = Field(None, max_length=200)
    latitude: Optional[str] = Field(None, max_length=20)
    longitude: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        if v:
            import re
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, v):
                raise ValueError("Invalid IP address format")
        return v


class RouterInDB(RouterBase):
    """Schema for router in database."""

    id: int
    status: RouterStatus
    is_active: bool
    uptime: int
    last_seen: Optional[datetime] = None
    config: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Router(RouterInDB):
    """Schema for router response."""

    devices: List[RouterDevice] = []


class RouterList(BaseModel):
    """Schema for router list response."""

    items: List[Router]
    total: int
    page: int
    size: int
    pages: int


class RouterStats(BaseModel):
    """Schema for router statistics."""

    router_id: int
    router_name: str
    status: str
    uptime: int
    active_subscriptions: int
    total_data_used: int
    last_seen: Optional[datetime] = None


class RouterLog(BaseModel):
    """Schema for router log."""

    id: int
    router_id: int
    action: str
    details: Optional[str] = None
    success: bool
    error_message: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RouterSyncRequest(BaseModel):
    """Schema for router sync request."""

    router_id: int


class RouterSyncResponse(BaseModel):
    """Schema for router sync response."""

    success: bool
    message: str
    router_id: int
    status: Optional[str] = None
    uptime: Optional[int] = None
    last_seen: Optional[datetime] = None
