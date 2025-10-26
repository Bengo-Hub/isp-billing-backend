"""User and role models."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserRole(str, PyEnum):
    """User role enumeration."""

    SUPERUSER = "superuser"
    ADMIN = "admin"
    TECHNICIAN = "technician"
    CUSTOMER = "customer"


class UserStatus(str, PyEnum):
    """User status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


class User(Base):
    """User model."""

    __tablename__ = "users"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Basic information
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    company_name = Column(String(200), nullable=True)  # For ISP providers
    
    # Authentication
    hashed_password = Column(String(255), nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Profile
    role = Column(Enum(UserRole), default=UserRole.CUSTOMER, nullable=False)
    status = Column(Enum(UserStatus), default=UserStatus.PENDING_VERIFICATION, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)  # RBAC role foreign key
    
    # Profile details
    avatar_url = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    last_login = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    email_verified_at = Column(DateTime, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
    
    # RBAC relationships
    role_obj = relationship("Role", back_populates="users", foreign_keys=[role_id])
    permission_overrides = relationship("UserPermission", back_populates="user", cascade="all, delete-orphan")
    
    # Business relationships - using lazy loading to avoid circular imports
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan", lazy="select", foreign_keys="Subscription.user_id")
    invoices = relationship("Invoice", back_populates="user", cascade="all, delete-orphan", lazy="select")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan", lazy="select", foreign_keys="Payment.user_id")
    tickets = relationship("SupportTicket", back_populates="user", cascade="all, delete-orphan", lazy="select", foreign_keys="SupportTicket.user_id")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan", lazy="select")

    @property
    def full_name(self) -> str:
        """Get user's full name."""
        return f"{self.first_name} {self.last_name}"

    def to_dict(self) -> dict:
        """Convert user model to dictionary."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "phone": self.phone,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "company_name": self.company_name,
            "role": self.role.value if self.role else None,
            "status": self.status.value if self.status else None,
            "is_verified": self.is_verified,
            "is_active": self.is_active,
            "avatar_url": self.avatar_url,
            "bio": self.bio,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "email_verified_at": self.email_verified_at.isoformat() if self.email_verified_at else None,
            "phone_verified_at": self.phone_verified_at.isoformat() if self.phone_verified_at else None,
            "full_name": self.full_name
        }

    def __repr__(self) -> str:
        """String representation."""
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class UserSession(Base):
    """User session model for tracking active sessions."""

    __tablename__ = "user_sessions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_token = Column(String(255), unique=True, index=True, nullable=False)
    refresh_token = Column(String(255), unique=True, index=True, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_activity = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", backref="sessions")

    def __repr__(self) -> str:
        """String representation."""
        return f"<UserSession(id={self.id}, user_id={self.user_id}, active={self.is_active})>"


class UserVerification(Base):
    """User verification tokens model."""

    __tablename__ = "user_verifications"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    verification_type = Column(String(20), nullable=False)  # email, phone, password_reset
    token = Column(String(255), unique=True, index=True, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", backref="verifications")

    def __repr__(self) -> str:
        """String representation."""
        return f"<UserVerification(id={self.id}, user_id={self.user_id}, type='{self.verification_type}')>"
