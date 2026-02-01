"""Leads and prospects model."""

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


class LeadStatus(str, PyEnum):
    """Lead status enumeration."""

    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CONVERTED = "converted"
    LOST = "lost"


class LeadSource(str, PyEnum):
    """Lead source enumeration."""

    WEBSITE = "website"
    REFERRAL = "referral"
    SOCIAL_MEDIA = "social_media"
    ADVERTISEMENT = "advertisement"
    WALK_IN = "walk_in"
    PHONE_CALL = "phone_call"
    OTHER = "other"


class Lead(Base):
    """Lead/prospect model with multi-tenant support."""

    __tablename__ = "leads"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization (tenant)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Contact information
    name = Column(String(200), nullable=False)
    email = Column(String(100), nullable=True, index=True)
    phone = Column(String(20), nullable=True, index=True)
    company = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)

    # Lead details
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW, nullable=False, index=True)
    source = Column(Enum(LeadSource), nullable=True)
    notes = Column(Text, nullable=True)
    estimated_value = Column(Integer, nullable=True)  # Potential revenue in cents

    # Assignment
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Conversion tracking
    converted_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Customer user created
    converted_at = Column(DateTime, nullable=True)

    # Metadata
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    last_contacted_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="leads")
    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id], back_populates="assigned_leads")
    converted_to_customer = relationship("User", foreign_keys=[converted_to_user_id], back_populates="converted_from_lead")
    created_by = relationship("User", foreign_keys=[created_by_user_id], back_populates="leads_created")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Lead(id={self.id}, name='{self.name}', status='{self.status}')>"
