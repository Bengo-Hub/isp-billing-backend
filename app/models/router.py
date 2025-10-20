"""Router and device models."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

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


class RouterStatus(str, PyEnum):
    """Router status enumeration."""

    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"
    ERROR = "error"


class RouterType(str, PyEnum):
    """Router type enumeration."""

    MIKROTIK = "mikrotik"
    CISCO = "cisco"
    UBIQUITI = "ubiquiti"
    OTHER = "other"


class Router(Base):
    """Router model."""

    __tablename__ = "routers"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Basic information
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    router_type = Column(Enum(RouterType), default=RouterType.MIKROTIK, nullable=False)
    
    # Network configuration
    ip_address = Column(String(45), nullable=False)
    port = Column(Integer, default=8728, nullable=False)
    username = Column(String(50), nullable=False)
    password = Column(String(255), nullable=False)  # Encrypted
    
    # Status and monitoring
    status = Column(Enum(RouterStatus), default=RouterStatus.OFFLINE, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_seen = Column(DateTime, nullable=True)
    uptime = Column(Integer, default=0, nullable=False)  # in seconds
    
    # Location
    location = Column(String(200), nullable=True)
    latitude = Column(String(20), nullable=True)
    longitude = Column(String(20), nullable=True)
    
    # Configuration
    config = Column(Text, nullable=True)  # JSON configuration
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="router", cascade="all, delete-orphan")
    devices = relationship("RouterDevice", back_populates="router", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Router(id={self.id}, name='{self.name}', ip='{self.ip_address}')>"


class RouterDevice(Base):
    """Router device model for tracking connected devices."""

    __tablename__ = "router_devices"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False)
    device_name = Column(String(100), nullable=False)
    device_type = Column(String(50), nullable=True)  # hotspot, pppoe, etc.
    mac_address = Column(String(17), nullable=True)
    ip_address = Column(String(45), nullable=True)
    is_online = Column(Boolean, default=False, nullable=False)
    last_seen = Column(DateTime, nullable=True)
    bytes_sent = Column(Integer, default=0, nullable=False)
    bytes_received = Column(Integer, default=0, nullable=False)
    uptime = Column(Integer, default=0, nullable=False)  # in seconds
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    router = relationship("Router", back_populates="devices")

    def __repr__(self) -> str:
        """String representation."""
        return f"<RouterDevice(id={self.id}, name='{self.device_name}', router_id={self.router_id})>"


class RouterLog(Base):
    """Router operation logs."""

    __tablename__ = "router_logs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False)
    action = Column(String(50), nullable=False)  # connect, disconnect, create_user, etc.
    details = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    router = relationship("Router", backref="logs")

    def __repr__(self) -> str:
        """String representation."""
        return f"<RouterLog(id={self.id}, router_id={self.router_id}, action='{self.action}')>"
