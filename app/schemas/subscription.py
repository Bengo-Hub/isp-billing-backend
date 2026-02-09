"""Subscription-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.subscription import SubscriptionStatus, SubscriptionType


class SubscriptionUsageLogBase(BaseModel):
    """Base subscription usage log schema."""

    log_date: datetime
    bytes_uploaded: int = Field(..., ge=0)
    bytes_downloaded: int = Field(..., ge=0)
    session_duration: int = Field(0, ge=0)
    ip_address: Optional[str] = Field(None, max_length=45)
    mac_address: Optional[str] = Field(None, max_length=17)


class SubscriptionUsageLogCreate(SubscriptionUsageLogBase):
    """Schema for creating subscription usage log."""
    pass


class SubscriptionUsageLog(SubscriptionUsageLogBase):
    """Schema for subscription usage log response."""

    id: int
    subscription_id: int
    # Note: created_at doesn't exist in the database model - using log_date as the timestamp

    class Config:
        from_attributes = True


class SubscriptionHistoryBase(BaseModel):
    """Base subscription history schema."""

    action: str = Field(..., min_length=1, max_length=50)
    details: Optional[str] = None
    changed_by: Optional[int] = None


class SubscriptionHistoryCreate(SubscriptionHistoryBase):
    """Schema for creating subscription history."""
    pass


class SubscriptionHistory(SubscriptionHistoryBase):
    """Schema for subscription history response."""

    id: int
    subscription_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriptionBase(BaseModel):
    """Base subscription schema."""

    user_id: int = Field(..., gt=0)
    plan_id: int = Field(..., gt=0)
    router_id: int = Field(..., gt=0)
    subscription_type: SubscriptionType = SubscriptionType.PPPOE
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=255)
    start_date: datetime
    end_date: datetime
    is_auto_renewal: bool = False
    notes: Optional[str] = None

    @validator("end_date")
    def validate_end_date(cls, v, values):
        """Validate end date is after start date."""
        if "start_date" in values and v <= values["start_date"]:
            raise ValueError("End date must be after start date")
        return v

    @validator("username")
    def validate_username(cls, v):
        """Validate username format."""
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("Username can only contain letters, numbers, underscores, and hyphens")
        return v


class SubscriptionCreate(SubscriptionBase):
    """Schema for creating a subscription."""
    pass


class SubscriptionUpdate(BaseModel):
    """Schema for updating a subscription."""

    plan_id: Optional[int] = Field(None, gt=0)
    router_id: Optional[int] = Field(None, gt=0)
    subscription_type: Optional[SubscriptionType] = None
    username: Optional[str] = Field(None, min_length=1, max_length=50)
    password: Optional[str] = Field(None, min_length=1, max_length=255)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_auto_renewal: Optional[bool] = None
    notes: Optional[str] = None

    @validator("username")
    def validate_username(cls, v):
        """Validate username format."""
        if v:
            import re
            if not re.match(r'^[a-zA-Z0-9_-]+$', v):
                raise ValueError("Username can only contain letters, numbers, underscores, and hyphens")
        return v


class SubscriptionInDB(SubscriptionBase):
    """Schema for subscription in database."""

    id: int
    status: SubscriptionStatus
    is_active: bool
    is_expired: bool
    is_router_synced: bool
    bytes_uploaded: int
    bytes_downloaded: int
    total_bytes_used: int
    total_data_used_gb: Decimal
    session_count: int
    last_activity: Optional[datetime] = None
    last_router_sync: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Subscription(SubscriptionInDB):
    """Schema for subscription response."""

    usage_logs: List[SubscriptionUsageLog] = []
    history: List[SubscriptionHistory] = []
    plan_name: Optional[str] = None
    router_name: Optional[str] = None


class SubscriptionStats(BaseModel):
    """Schema for subscription statistics."""

    subscription_id: int
    username: str
    status: str
    total_bytes_used: int
    total_data_used_gb: Decimal
    session_count: int
    monthly_uploaded: int
    monthly_downloaded: int
    last_activity: Optional[datetime] = None
    start_date: datetime
    end_date: datetime
    is_active: bool
    is_expired: bool


class SubscriptionList(BaseModel):
    """Schema for subscription list response."""

    subscriptions: List[Subscription]
    total: int
    page: int
    size: int
    pages: int


class SubscriptionFilter(BaseModel):
    """Schema for subscription filters."""

    user_id: Optional[int] = None
    plan_id: Optional[int] = None
    router_id: Optional[int] = None
    status: Optional[SubscriptionStatus] = None
    subscription_type: Optional[SubscriptionType] = None
    search: Optional[str] = None
    is_active: Optional[bool] = None
    is_expired: Optional[bool] = None


class SubscriptionRenewalRequest(BaseModel):
    """Schema for subscription renewal request."""

    subscription_id: int
    new_end_date: datetime
    notes: Optional[str] = None

    @validator("new_end_date")
    def validate_new_end_date(cls, v):
        """Validate new end date is in the future."""
        if v <= datetime.utcnow():
            raise ValueError("New end date must be in the future")
        return v


class SubscriptionSuspendRequest(BaseModel):
    """Schema for subscription suspension request."""

    subscription_id: int
    reason: Optional[str] = None


class SubscriptionCancelRequest(BaseModel):
    """Schema for subscription cancellation request."""

    subscription_id: int
    reason: Optional[str] = None


class SubscriptionUsageUpdate(BaseModel):
    """Schema for updating subscription usage."""

    subscription_id: int
    bytes_uploaded: int = Field(..., ge=0)
    bytes_downloaded: int = Field(..., ge=0)
    session_duration: int = Field(0, ge=0)
    ip_address: Optional[str] = Field(None, max_length=45)
    mac_address: Optional[str] = Field(None, max_length=17)
