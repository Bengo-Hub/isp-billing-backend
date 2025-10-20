"""Support ticket-related Pydantic schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.notification import TicketStatus, TicketPriority


class TicketMessageBase(BaseModel):
    """Base ticket message schema."""

    message: str = Field(..., min_length=1, max_length=5000)
    is_internal: bool = False
    attachments: Optional[str] = None
    ip_address: Optional[str] = Field(None, max_length=45)


class TicketMessageCreate(TicketMessageBase):
    """Schema for creating a ticket message."""
    pass


class TicketMessageUpdate(BaseModel):
    """Schema for updating a ticket message."""

    message: Optional[str] = Field(None, min_length=1, max_length=5000)
    is_internal: Optional[bool] = None
    attachments: Optional[str] = None


class TicketMessage(TicketMessageBase):
    """Schema for ticket message response."""

    id: int
    ticket_id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SupportTicketBase(BaseModel):
    """Base support ticket schema."""

    user_id: int = Field(..., gt=0)
    subject: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    category: Optional[str] = Field(None, max_length=100)
    priority: TicketPriority = TicketPriority.MEDIUM
    tags: Optional[str] = Field(None, max_length=500)
    attachments: Optional[str] = None

    @validator("category")
    def validate_category(cls, v):
        """Validate category."""
        if v:
            allowed_categories = [
                "technical", "billing", "account", "service", "general", "complaint", "suggestion"
            ]
            if v.lower() not in allowed_categories:
                raise ValueError(f"Category must be one of: {', '.join(allowed_categories)}")
        return v

    @validator("tags")
    def validate_tags(cls, v):
        """Validate tags format."""
        if v:
            # Tags should be comma-separated
            tags = [tag.strip() for tag in v.split(",")]
            if len(tags) > 10:
                raise ValueError("Maximum 10 tags allowed")
            for tag in tags:
                if len(tag) > 50:
                    raise ValueError("Each tag must be 50 characters or less")
        return v


class SupportTicketCreate(SupportTicketBase):
    """Schema for creating a support ticket."""
    pass


class SupportTicketUpdate(BaseModel):
    """Schema for updating a support ticket."""

    subject: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1, max_length=5000)
    category: Optional[str] = Field(None, max_length=100)
    priority: Optional[TicketPriority] = None
    tags: Optional[str] = Field(None, max_length=500)
    attachments: Optional[str] = None

    @validator("category")
    def validate_category(cls, v):
        """Validate category."""
        if v:
            allowed_categories = [
                "technical", "billing", "account", "service", "general", "complaint", "suggestion"
            ]
            if v.lower() not in allowed_categories:
                raise ValueError(f"Category must be one of: {', '.join(allowed_categories)}")
        return v

    @validator("tags")
    def validate_tags(cls, v):
        """Validate tags format."""
        if v:
            # Tags should be comma-separated
            tags = [tag.strip() for tag in v.split(",")]
            if len(tags) > 10:
                raise ValueError("Maximum 10 tags allowed")
            for tag in tags:
                if len(tag) > 50:
                    raise ValueError("Each tag must be 50 characters or less")
        return v


class SupportTicketInDB(SupportTicketBase):
    """Schema for support ticket in database."""

    id: int
    ticket_number: str
    status: TicketStatus
    assigned_to: Optional[int] = None
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SupportTicket(SupportTicketInDB):
    """Schema for support ticket response."""

    messages: List[TicketMessage] = []


class SupportTicketList(BaseModel):
    """Schema for support ticket list response."""

    tickets: List[SupportTicket]
    total: int
    page: int
    size: int
    pages: int


class SupportTicketFilter(BaseModel):
    """Schema for support ticket filters."""

    user_id: Optional[int] = None
    assigned_to: Optional[int] = None
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    category: Optional[str] = None
    search: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class TicketAssignmentRequest(BaseModel):
    """Schema for ticket assignment request."""

    ticket_id: int
    assigned_to: int

    @validator("assigned_to")
    def validate_assigned_to(cls, v):
        """Validate assigned_to is positive."""
        if v <= 0:
            raise ValueError("assigned_to must be a positive integer")
        return v


class TicketResolutionRequest(BaseModel):
    """Schema for ticket resolution request."""

    ticket_id: int
    resolution: str = Field(..., min_length=1, max_length=2000)


class TicketCloseRequest(BaseModel):
    """Schema for ticket close request."""

    ticket_id: int


class TicketCancelRequest(BaseModel):
    """Schema for ticket cancellation request."""

    ticket_id: int
    reason: Optional[str] = Field(None, max_length=500)


class TicketStats(BaseModel):
    """Schema for ticket statistics."""

    total_tickets: int
    open_tickets: int
    in_progress_tickets: int
    resolved_tickets: int
    closed_tickets: int
    avg_resolution_time_hours: float
    resolution_rate: float


class TicketStatsByPriority(BaseModel):
    """Schema for ticket statistics by priority."""

    low: int = 0
    medium: int = 0
    high: int = 0
    urgent: int = 0


class TicketStatsByCategory(BaseModel):
    """Schema for ticket statistics by category."""

    technical: int = 0
    billing: int = 0
    account: int = 0
    service: int = 0
    general: int = 0
    complaint: int = 0
    suggestion: int = 0


class TicketDashboard(BaseModel):
    """Schema for ticket dashboard data."""

    stats: TicketStats
    stats_by_priority: TicketStatsByPriority
    stats_by_category: TicketStatsByCategory
    recent_tickets: List[SupportTicket]
    open_tickets: List[SupportTicket]


class TicketSearchRequest(BaseModel):
    """Schema for ticket search request."""

    query: str = Field(..., min_length=1, max_length=100)
    category: Optional[str] = None
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    user_id: Optional[int] = None
    assigned_to: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
