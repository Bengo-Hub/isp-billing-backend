"""System activity logs Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.system_log import LogLevel


class SystemLogBase(BaseModel):
    """Base system log schema."""

    level: LogLevel = Field(..., description="Log level")
    message: str = Field(..., min_length=1, max_length=500, description="Log message")
    details: Optional[str] = Field(None, description="Additional details")
    user_email: Optional[str] = Field(None, max_length=100, description="User email")
    ip_address: Optional[str] = Field(None, max_length=45, description="IP address")
    action: Optional[str] = Field(None, max_length=100, description="Action performed")
    entity_type: Optional[str] = Field(None, max_length=50, description="Entity type")
    entity_id: Optional[int] = Field(None, description="Entity ID")


class SystemLogCreate(SystemLogBase):
    """Schema for creating a system log."""
    pass


class SystemLog(SystemLogBase):
    """Schema for system log response."""

    id: int
    organization_id: int
    user_id: Optional[int] = None
    timestamp: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class SystemLogListResponse(BaseModel):
    """Schema for paginated system log list response."""

    items: list[SystemLog]
    total: int
    page: int
    size: int
    pages: int
    stats: Optional[dict] = None

    class Config:
        from_attributes = True


class SystemLogStats(BaseModel):
    """Schema for system log statistics."""

    error_count: int
    warning_count: int
    info_count: int
    success_count: int
    total_logs: int

    class Config:
        from_attributes = True
