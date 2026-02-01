"""Email tracking Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, EmailStr

from app.models.email import EmailStatus


class EmailBase(BaseModel):
    """Base email schema."""

    to_email: EmailStr = Field(..., description="Recipient email address")
    to_name: Optional[str] = Field(None, max_length=200, description="Recipient name")
    cc: Optional[str] = Field(None, description="CC emails (comma-separated)")
    bcc: Optional[str] = Field(None, description="BCC emails (comma-separated)")
    subject: str = Field(..., min_length=1, max_length=500, description="Email subject")
    body_text: Optional[str] = Field(None, description="Plain text body")
    body_html: Optional[str] = Field(None, description="HTML body")
    attachments: Optional[str] = Field(None, description="Attachments JSON array")
    template_name: Optional[str] = Field(None, max_length=100, description="Template name")
    template_data: Optional[str] = Field(None, description="Template data JSON")
    campaign_id: Optional[int] = Field(None, description="Associated campaign ID")


class EmailCreate(EmailBase):
    """Schema for creating/sending an email."""
    pass


class Email(EmailBase):
    """Schema for email response."""

    id: int
    organization_id: int
    status: EmailStatus
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    bounced_at: Optional[datetime] = None
    external_message_id: Optional[str] = None
    external_tracking_id: Optional[str] = None
    user_id: Optional[int] = None
    sent_by_user_id: Optional[int] = None
    retry_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmailListResponse(BaseModel):
    """Schema for paginated email list response."""

    items: list[Email]
    total: int
    page: int
    size: int
    pages: int

    class Config:
        from_attributes = True


class EmailTemplateBase(BaseModel):
    """Base email template schema."""

    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    subject: str = Field(..., min_length=1, max_length=500, description="Template subject")
    body_html: str = Field(..., description="HTML body template")
    body_text: Optional[str] = Field(None, description="Plain text template")
    description: Optional[str] = Field(None, description="Template description")


class EmailTemplateCreate(EmailTemplateBase):
    """Schema for creating an email template."""
    pass


class EmailTemplate(EmailTemplateBase):
    """Schema for email template response."""

    id: int
    organization_id: int
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
