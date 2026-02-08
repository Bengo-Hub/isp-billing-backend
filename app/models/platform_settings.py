"""Platform settings model for platform owner configuration (singleton)."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class PlatformSettings(Base):
    """
    Singleton platform settings for the ISP billing platform owner.

    Stores company information, branding, and invoice configuration.
    Only one row should exist - seeded on startup.
    """

    __tablename__ = "platform_settings"

    id = Column(Integer, primary_key=True, index=True)

    # Company information
    company_name = Column(String(200), nullable=False, default="CodeVertex IT Solutions")
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), default="Kenya", nullable=False)
    phone = Column(String(20), nullable=True)
    mobile = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    website_url = Column(String(500), nullable=True)

    # Branding
    logo_url = Column(String(500), nullable=True, default="/images/logo/logo.png")
    favicon_url = Column(String(500), nullable=True)
    primary_color = Column(String(7), default="#ec4899", nullable=False)
    secondary_color = Column(String(7), default="#8b5cf6", nullable=True)

    # Invoice configuration
    invoice_prefix = Column(String(10), default="INV", nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0, nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    terms_of_service = Column(Text, nullable=True)
    privacy_policy_url = Column(String(500), nullable=True)

    # Platform defaults
    default_trial_days = Column(Integer, default=14, nullable=False)
    default_grace_period_days = Column(Integer, default=2, nullable=False)

    # Linked admin user
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    admin_user = relationship("User", foreign_keys=[admin_user_id])

    def __repr__(self) -> str:
        return f"<PlatformSettings(id={self.id}, company='{self.company_name}')>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_name": self.company_name,
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "phone": self.phone,
            "mobile": self.mobile,
            "email": self.email,
            "website_url": self.website_url,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "invoice_prefix": self.invoice_prefix,
            "tax_rate": float(self.tax_rate) if self.tax_rate else 0,
            "currency": self.currency,
            "default_trial_days": self.default_trial_days,
            "default_grace_period_days": self.default_grace_period_days,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
