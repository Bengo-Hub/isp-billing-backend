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

    INTERNET = "INTERNET"
    HOTSPOT = "HOTSPOT"
    PPPOE = "PPPOE"
    BOTH = "BOTH"


class BillingCycle(str, PyEnum):
    """Billing cycle enumeration."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"
    ONE_TIME = "ONE_TIME"


class PlanStatus(str, PyEnum):
    """Plan status enumeration."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ServicePlan(Base):
    """Service plan model with multi-tenant support."""

    __tablename__ = "service_plans"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization (tenant)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)

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
    
    # Template features
    is_template = Column(Boolean, default=False, nullable=False)  # Is this a predefined template?
    template_category = Column(String(50), nullable=True)  # popular, business, trial, etc.
    enable_burst = Column(Boolean, default=False, nullable=False)
    burst_download = Column(Integer, nullable=True)  # Mbps
    burst_upload = Column(Integer, nullable=True)  # Mbps
    burst_threshold = Column(Integer, nullable=True)  # percentage
    burst_time = Column(Integer, nullable=True)  # seconds
    enable_schedule = Column(Boolean, default=False, nullable=False)
    schedule_start_time = Column(String(5), nullable=True)  # HH:MM format
    schedule_end_time = Column(String(5), nullable=True)  # HH:MM format
    
    # Configuration
    config = Column(Text, nullable=True)  # JSON configuration for router
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="service_plans")
    subscriptions = relationship("Subscription", back_populates="plan", cascade="all, delete-orphan")
    features = relationship("PlanFeature", backref="plan", cascade="all, delete-orphan")
    pricing_tiers = relationship("PlanPricing", backref="plan", cascade="all, delete-orphan")

    @property
    def pricing(self):
        """Backward-compatible alias for pricing tiers."""
        return self.pricing_tiers

    @property
    def is_unlimited_data(self) -> bool:
        """Check if plan has unlimited data."""
        return self.data_limit == -1

    @property
    def is_unlimited_time(self) -> bool:
        """Check if plan has unlimited time."""
        return self.time_limit == -1

    def access_window_hours(self) -> int:
        """Effective access window, in HOURS, for a hotspot package.

        ``validity_days`` is the calendar window; ``time_limit`` (also HOURS, per
        the column definition) caps it when set (> 0). Returns the binding duration
        in hours, or <= 0 when no finite window is defined (e.g. unlimited) so the
        caller can treat it as "no calendar expiry". This is the single source of
        truth used by both the voucher-redeem expiry and the expiry reconciler.
        """
        hours = (self.validity_days or 0) * 24
        if self.time_limit and self.time_limit > 0:
            hours = min(hours, self.time_limit) if hours > 0 else self.time_limit
        return hours

    def access_expiry_from(self, activated_at, fallback_churn_days: int | None = None):
        """Absolute access expiry for a package activated at ``activated_at``.

        When the plan defines a finite window (validity_days / time_limit) that
        binds. Otherwise — a plan with NO specific duration — we churn the user
        after ``fallback_churn_days`` (the ISP's configured auto_suspend_days,
        default 14) so unlimited/duration-less packages don't grant access
        forever. Returns ``None`` only when there is neither a plan window nor a
        churn fallback (caller then relies purely on router-side limits).
        """
        from datetime import timedelta

        hours = self.access_window_hours()
        if hours > 0:
            return activated_at + timedelta(hours=hours)
        if fallback_churn_days and fallback_churn_days > 0:
            return activated_at + timedelta(days=fallback_churn_days)
        return None

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
