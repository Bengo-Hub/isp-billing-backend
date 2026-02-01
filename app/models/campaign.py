"""Marketing campaigns model."""

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
    Date,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class CampaignType(str, PyEnum):
    """Campaign type enumeration."""

    SMS = "sms"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    BOTH = "both"  # SMS + Email


class CampaignStatus(str, PyEnum):
    """Campaign status enumeration."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Campaign(Base):
    """Marketing campaign model with multi-tenant support."""

    __tablename__ = "campaigns"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization (tenant)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Campaign details
    name = Column(String(200), nullable=False)
    campaign_type = Column(Enum(CampaignType), nullable=False)
    status = Column(Enum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False, index=True)

    # Scheduling
    scheduled_date = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Recipients and statistics
    recipients_count = Column(Integer, default=0, nullable=False)
    sent_count = Column(Integer, default=0, nullable=False)
    delivered_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    opened_count = Column(Integer, default=0, nullable=False)  # For email campaigns
    clicked_count = Column(Integer, default=0, nullable=False)  # For email campaigns

    # Content
    message_content = Column(Text, nullable=True)  # SMS/WhatsApp content
    email_subject = Column(String(200), nullable=True)  # Email subject
    email_content = Column(Text, nullable=True)  # Email HTML content

    # Target audience filters (stored as JSON-like text or can be JSON column)
    target_filters = Column(Text, nullable=True)  # e.g., "status=active,plan_type=hotspot"

    # Metadata
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="campaigns")
    created_by = relationship("User", back_populates="campaigns_created", foreign_keys=[created_by_user_id])
    emails = relationship("Email", back_populates="campaign", lazy="select")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Campaign(id={self.id}, name='{self.name}', type='{self.campaign_type}', status='{self.status}')>"
