"""System activity logs model."""

from datetime import datetime
from enum import Enum as PyEnum

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


class LogLevel(str, PyEnum):
    """Log level enumeration."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUCCESS = "success"


class SystemLog(Base):
    """System activity logs with multi-tenant support."""

    __tablename__ = "system_logs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization (tenant)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Log details
    level = Column(Enum(LogLevel), nullable=False, index=True)
    message = Column(String(500), nullable=False)
    details = Column(Text, nullable=True)

    # Context information
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_email = Column(String(100), nullable=True)  # Denormalized for performance
    ip_address = Column(String(45), nullable=True)
    action = Column(String(100), nullable=True)  # e.g., "user_login", "invoice_created", etc.
    entity_type = Column(String(50), nullable=True)  # e.g., "user", "invoice", "router", etc.
    entity_id = Column(Integer, nullable=True)

    # Timestamps
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="system_logs")
    user = relationship("User", back_populates="system_logs", foreign_keys=[user_id])

    def __repr__(self) -> str:
        """String representation."""
        return f"<SystemLog(id={self.id}, level='{self.level}', action='{self.action}')>"
