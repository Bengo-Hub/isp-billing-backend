"""Email tracking model."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class EmailStatus(str, PyEnum):
    """Email status enumeration."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    OPENED = "opened"
    CLICKED = "clicked"


class Email(Base):
    """Email tracking model with multi-tenant support."""

    __tablename__ = "emails"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization (tenant)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Recipient
    to_email = Column(String(255), nullable=False, index=True)
    to_name = Column(String(200), nullable=True)
    cc = Column(Text, nullable=True)  # Comma-separated emails
    bcc = Column(Text, nullable=True)  # Comma-separated emails

    # Content
    subject = Column(String(500), nullable=False)
    body_text = Column(Text, nullable=True)  # Plain text version
    body_html = Column(Text, nullable=True)  # HTML version

    # Attachments
    attachments = Column(Text, nullable=True)  # JSON array of file paths

    # Status tracking
    status = Column(Enum(EmailStatus), default=EmailStatus.PENDING, nullable=False, index=True)
    error_message = Column(Text, nullable=True)

    # Delivery tracking
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    clicked_at = Column(DateTime, nullable=True)
    bounced_at = Column(DateTime, nullable=True)

    # External service tracking
    external_message_id = Column(String(255), nullable=True)  # Email service provider ID
    external_tracking_id = Column(String(255), nullable=True)

    # Template information
    template_name = Column(String(100), nullable=True)
    template_data = Column(Text, nullable=True)  # JSON data

    # Campaign association
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)

    # User association
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Recipient user if exists
    sent_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Staff who sent

    # Metadata
    retry_count = Column(Integer, default=0, nullable=False)
    extra_data = Column(Text, nullable=True)  # JSON metadata

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="emails")
    campaign = relationship("Campaign", back_populates="emails")
    user = relationship("User", foreign_keys=[user_id], back_populates="emails_received")
    sent_by = relationship("User", foreign_keys=[sent_by_user_id], back_populates="emails_sent")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Email(id={self.id}, to='{self.to_email}', subject='{self.subject[:50]}', status='{self.status}')>"
