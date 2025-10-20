"""Subscription models for user service assignments."""

from enum import Enum as PyEnum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class SubscriptionStatus(str, PyEnum):
    """Subscription status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PENDING = "pending"


class SubscriptionType(str, PyEnum):
    """Subscription type enumeration."""

    HOTSPOT = "hotspot"
    PPPOE = "pppoe"


class Subscription(Base):
    """User subscription model."""

    __tablename__ = "subscriptions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=False)
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False)
    
    # Subscription details
    subscription_type = Column(Enum(SubscriptionType), nullable=False)
    status = Column(Enum(SubscriptionStatus), default=SubscriptionStatus.PENDING, nullable=False)
    
    # User credentials for router
    username = Column(String(50), nullable=False)
    password = Column(String(255), nullable=False)  # Encrypted
    
    # Validity period
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_auto_renewal = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Usage tracking
    bytes_uploaded = Column(Integer, default=0, nullable=False)
    bytes_downloaded = Column(Integer, default=0, nullable=False)
    total_bytes_used = Column(Integer, default=0, nullable=False)
    session_count = Column(Integer, default=0, nullable=False)
    last_activity = Column(DateTime, nullable=True)
    
    # Router-specific configuration
    router_config = Column(Text, nullable=True)  # JSON configuration
    is_router_synced = Column(Boolean, default=False, nullable=False)
    last_router_sync = Column(DateTime, nullable=True)
    
    # Notes and metadata
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "router_id", "subscription_type", name="uq_user_router_type"),
    )

    # Relationships
    user = relationship("User", back_populates="subscriptions", foreign_keys=[user_id])
    plan = relationship("ServicePlan", back_populates="subscriptions")
    router = relationship("Router", back_populates="subscriptions")
    creator = relationship("User", foreign_keys=[created_by])
    usage_logs = relationship("SubscriptionUsageLog", back_populates="subscription", cascade="all, delete-orphan")

    @property
    def is_active(self) -> bool:
        """Check if subscription is active."""
        return (
            self.status == SubscriptionStatus.ACTIVE
            and self.end_date > datetime.utcnow()
        )

    @property
    def is_expired(self) -> bool:
        """Check if subscription is expired."""
        return self.end_date <= datetime.utcnow()

    @property
    def total_data_used_gb(self) -> float:
        """Get total data used in GB."""
        return self.total_bytes_used / (1024 ** 3)

    def __repr__(self) -> str:
        """String representation."""
        return f"<Subscription(id={self.id}, user_id={self.user_id}, type='{self.subscription_type}')>"


class SubscriptionUsageLog(Base):
    """Subscription usage tracking logs."""

    __tablename__ = "subscription_usage_logs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    log_date = Column(DateTime, nullable=False)
    bytes_uploaded = Column(Integer, default=0, nullable=False)
    bytes_downloaded = Column(Integer, default=0, nullable=False)
    session_duration = Column(Integer, default=0, nullable=False)  # in seconds
    ip_address = Column(String(45), nullable=True)
    mac_address = Column(String(17), nullable=True)

    # Relationships
    subscription = relationship("Subscription", back_populates="usage_logs")

    def __repr__(self) -> str:
        """String representation."""
        return f"<SubscriptionUsageLog(id={self.id}, subscription_id={self.subscription_id}, date={self.log_date})>"


class SubscriptionHistory(Base):
    """Subscription change history."""

    __tablename__ = "subscription_history"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    action = Column(String(50), nullable=False)  # created, activated, suspended, etc.
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    details = Column(Text, nullable=True)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(45), nullable=True)

    # Relationships
    subscription = relationship("Subscription", backref="history")
    changer = relationship("User", foreign_keys=[changed_by])

    def __repr__(self) -> str:
        """String representation."""
        return f"<SubscriptionHistory(id={self.id}, subscription_id={self.subscription_id}, action='{self.action}')>"
