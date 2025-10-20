"""Notification-related Pydantic schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.notification import NotificationType, NotificationStatus, NotificationPriority


class NotificationBase(BaseModel):
    """Base notification schema."""

    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=2000)
    notification_type: NotificationType = NotificationType.INFO
    priority: NotificationPriority = NotificationPriority.MEDIUM
    data: Optional[Dict[str, Any]] = None


class NotificationCreate(NotificationBase):
    """Schema for creating a notification."""

    user_id: int = Field(..., gt=0)


class NotificationUpdate(BaseModel):
    """Schema for updating a notification."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    message: Optional[str] = Field(None, min_length=1, max_length=2000)
    notification_type: Optional[NotificationType] = None
    priority: Optional[NotificationPriority] = None
    data: Optional[Dict[str, Any]] = None


class NotificationInDB(NotificationBase):
    """Schema for notification in database."""

    id: int
    user_id: int
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Notification(NotificationInDB):
    """Schema for notification response."""
    pass


class NotificationList(BaseModel):
    """Schema for notification list response."""

    notifications: List[Notification]
    total: int
    page: int
    size: int
    pages: int


class NotificationFilter(BaseModel):
    """Schema for notification filters."""

    notification_type: Optional[NotificationType] = None
    is_read: Optional[bool] = None
    priority: Optional[NotificationPriority] = None
    search: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class NotificationTemplateBase(BaseModel):
    """Base notification template schema."""

    name: str = Field(..., min_length=1, max_length=100)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=5000)
    notification_type: NotificationType = NotificationType.INFO
    is_active: bool = True
    variables: Optional[Dict[str, str]] = None


class NotificationTemplateCreate(NotificationTemplateBase):
    """Schema for creating a notification template."""
    pass


class NotificationTemplateUpdate(BaseModel):
    """Schema for updating a notification template."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    subject: Optional[str] = Field(None, min_length=1, max_length=200)
    body: Optional[str] = Field(None, min_length=1, max_length=5000)
    notification_type: Optional[NotificationType] = None
    is_active: Optional[bool] = None
    variables: Optional[Dict[str, str]] = None


class NotificationTemplate(NotificationTemplateBase):
    """Schema for notification template response."""

    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmailNotificationRequest(BaseModel):
    """Schema for email notification request."""

    to_email: str = Field(..., min_length=5, max_length=100)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=5000)
    is_html: bool = False
    attachments: Optional[List[str]] = None

    @validator("to_email")
    def validate_email(cls, v):
        """Validate email format."""
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, v):
            raise ValueError("Invalid email format")
        return v


class SMSNotificationRequest(BaseModel):
    """Schema for SMS notification request."""

    to_phone: str = Field(..., min_length=10, max_length=15)
    message: str = Field(..., min_length=1, max_length=160)

    @validator("to_phone")
    def validate_phone(cls, v):
        """Validate phone number format."""
        import re
        # Remove any non-digit characters
        phone = re.sub(r'\D', '', v)
        # Check if it's a valid phone number
        if not re.match(r'^(254|0)[0-9]{9}$', phone):
            raise ValueError("Invalid phone number format")
        return phone


class NotificationStats(BaseModel):
    """Schema for notification statistics."""

    total_notifications: int
    unread_notifications: int
    read_notifications: int
    notifications_by_type: Dict[str, int]
    notifications_by_priority: Dict[str, int]


class BulkNotificationRequest(BaseModel):
    """Schema for bulk notification request."""

    user_ids: List[int] = Field(..., min_items=1)
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=2000)
    notification_type: NotificationType = NotificationType.INFO
    priority: NotificationPriority = NotificationPriority.MEDIUM
    data: Optional[Dict[str, Any]] = None
