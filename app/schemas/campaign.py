"""Campaign Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.campaign import CampaignType, CampaignStatus


class CampaignBase(BaseModel):
    """Base campaign schema."""

    name: str = Field(..., min_length=1, max_length=200, description="Campaign name")
    campaign_type: CampaignType = Field(..., description="Campaign type")
    message_content: Optional[str] = Field(None, description="SMS/WhatsApp message content")
    email_subject: Optional[str] = Field(None, max_length=200, description="Email subject")
    email_content: Optional[str] = Field(None, description="Email HTML content")
    target_filters: Optional[str] = Field(None, description="Target audience filters")
    scheduled_date: Optional[datetime] = Field(None, description="Scheduled send date/time")
    notes: Optional[str] = Field(None, description="Campaign notes")


class CampaignCreate(CampaignBase):
    """Schema for creating a campaign."""
    pass


class CampaignUpdate(BaseModel):
    """Schema for updating a campaign."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    campaign_type: Optional[CampaignType] = None
    status: Optional[CampaignStatus] = None
    message_content: Optional[str] = None
    email_subject: Optional[str] = Field(None, max_length=200)
    email_content: Optional[str] = None
    target_filters: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    notes: Optional[str] = None


class Campaign(CampaignBase):
    """Schema for campaign response."""

    id: int
    organization_id: int
    status: CampaignStatus
    scheduled_date: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    recipients_count: int
    sent_count: int
    delivered_count: int
    failed_count: int
    opened_count: int
    clicked_count: int
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CampaignListResponse(BaseModel):
    """Schema for paginated campaign list response."""

    items: list[Campaign]
    total: int
    page: int
    size: int
    pages: int

    class Config:
        from_attributes = True


class CampaignAnalytics(BaseModel):
    """Schema for campaign analytics."""

    campaign_id: int
    recipients_count: int
    sent_count: int
    delivered_count: int
    failed_count: int
    opened_count: int
    clicked_count: int
    delivery_rate: float
    open_rate: float
    click_rate: float

    class Config:
        from_attributes = True
