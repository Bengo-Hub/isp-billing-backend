"""Expense tracking models."""
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Date,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ExpenseStatus(str, PyEnum):
    """Expense status enumeration."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExpenseCategory(str, PyEnum):
    """Expense category enumeration."""

    INFRASTRUCTURE = "INFRASTRUCTURE"
    EQUIPMENT = "EQUIPMENT"
    MAINTENANCE = "MAINTENANCE"
    UTILITIES = "UTILITIES"
    LICENSES = "LICENSES"
    MARKETING = "MARKETING"
    SALARIES = "SALARIES"
    OFFICE = "OFFICE"
    TRAVEL = "TRAVEL"
    OTHER = "OTHER"


class Expense(Base):
    """Expense model with multi-tenant support."""

    __tablename__ = "expenses"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization (tenant)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Expense details
    date = Column(Date, nullable=False, index=True)
    category = Column(Enum(ExpenseCategory), nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)

    # Additional information
    receipt_url = Column(String(500), nullable=True)
    added_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(ExpenseStatus), default=ExpenseStatus.PENDING, nullable=False)
    notes = Column(Text, nullable=True)

    # Approval tracking
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="expenses")
    added_by = relationship("User", foreign_keys=[added_by_user_id], back_populates="expenses_added")
    approved_by = relationship("User", foreign_keys=[approved_by_user_id], back_populates="expenses_approved")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Expense(id={self.id}, category='{self.category}', amount={self.amount}, status='{self.status}')>"
