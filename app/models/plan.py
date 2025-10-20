"""Service plans and packages models."""
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class PlanType(str, PyEnum):
    """Plan type enumeration."""

    INTERNET = "internet"
    HOTSPOT = "hotspot"
    PPPOE = "pppoe"
    BOTH = "both"


class BillingCycle(str, PyEnum):
    """Billing cycle enumeration."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    ONE_TIME = "one_time"


class PlanStatus(str, PyEnum):
    """Plan status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


class ServicePlan(Base):
    """Service plan model."""

    __tablename__ = "service_plans"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Basic information
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    plan_type = Column(Enum(PlanType), nullable=False)
    status = Column(Enum(PlanStatus), default=PlanStatus.ACTIVE, nullable=False)
    
    # Pricing
    price = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    billing_cycle = Column(Enum(BillingCycle), nullable=False)
    
    # Bandwidth limits (in Mbps)
    download_speed = Column(Integer, nullable=False)
    upload_speed = Column(Integer, nullable=False)
    
    # Data limits (in GB, -1 for unlimited)
    data_limit = Column(Integer, default=-1, nullable=False)
    data_limit_type = Column(String(20), default="total", nullable=False)  # total, daily, monthly
    
    # Time limits (in hours, -1 for unlimited)
    time_limit = Column(Integer, default=-1, nullable=False)
    time_limit_type = Column(String(20), default="total", nullable=False)  # total, daily, monthly
    
    # Validity period (in days)
    validity_days = Column(Integer, nullable=False)
    
    # Fair Usage Policy (FUP)
    fup_enabled = Column(Boolean, default=False, nullable=False)
    fup_threshold = Column(Integer, nullable=True)  # in GB
    fup_download_speed = Column(Integer, nullable=True)  # in Mbps
    fup_upload_speed = Column(Integer, nullable=True)  # in Mbps
    
    # Additional features
    concurrent_sessions = Column(Integer, default=1, nullable=False)
    auto_renewal = Column(Boolean, default=False, nullable=False)
    is_popular = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    
    # Configuration
    config = Column(Text, nullable=True)  # JSON configuration for router
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="plan", cascade="all, delete-orphan")

    @property
    def is_unlimited_data(self) -> bool:
        """Check if plan has unlimited data."""
        return self.data_limit == -1

    @property
    def is_unlimited_time(self) -> bool:
        """Check if plan has unlimited time."""
        return self.time_limit == -1

    def __repr__(self) -> str:
        """String representation."""
        return f"<ServicePlan(id={self.id}, name='{self.name}', type='{self.plan_type}')>"


class PlanFeature(Base):
    """Plan features model."""

    __tablename__ = "plan_features"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=False)
    feature_name = Column(String(100), nullable=False)
    feature_value = Column(String(200), nullable=True)
    is_included = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<PlanFeature(id={self.id}, plan_id={self.plan_id}, name='{self.feature_name}')>"


class PlanPricing(Base):
    """Plan pricing tiers model."""

    __tablename__ = "plan_pricing"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=False)
    duration_months = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    discount_percentage = Column(Numeric(5, 2), default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<PlanPricing(id={self.id}, plan_id={self.plan_id}, duration={self.duration_months} months)>"
