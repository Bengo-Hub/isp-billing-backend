"""Router and device models."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    BigInteger,
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
    """Router model with multi-tenant support."""

    __tablename__ = "routers"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization (tenant)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)

    # Basic information
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    router_type = Column(Enum(RouterType), default=RouterType.MIKROTIK, nullable=False)
    
    # Network configuration
    ip_address = Column(String(45), nullable=False)
    port = Column(Integer, default=8728, nullable=False)  # API port
    username = Column(String(50), nullable=False)
    password = Column(String(255), nullable=False)  # Encrypted

    # Remote Winbox access (VPN tunnel)
    winbox_port = Column(Integer, nullable=True, unique=True)  # Unique VPN port for remote Winbox (e.g., 51255)

    # WireGuard VPN overlay (router management tunnel).
    # Routers dial our WG server outbound (NAT-safe) and keep their OWN private
    # key — only the PUBLIC key is stored here (no secret material at rest).
    # vpn_address is the per-router tunnel IP (e.g. 10.8.0.7); once vpn_enabled
    # the backend addresses the router over the tunnel (direct API + winbox).
    vpn_address = Column(String(45), nullable=True, unique=True)  # tunnel IP 10.8.0.<n>
    vpn_public_key = Column(String(64), nullable=True)  # router's WG public key (base64)
    vpn_enabled = Column(Boolean, default=False, nullable=False)  # tunnel established + usable
    
    # Status and monitoring
    status = Column(Enum(RouterStatus), default=RouterStatus.OFFLINE, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_seen = Column(DateTime, nullable=True)
    uptime = Column(Integer, default=0, nullable=False)  # in seconds

    # System resource information (from /system/resource)
    routeros_version = Column(String(50), nullable=True)  # e.g., "7.18.2 (stable)"
    board_name = Column(String(100), nullable=True)  # e.g., "RB951Ui-2HnD"
    architecture = Column(String(50), nullable=True)  # e.g., "mipsbe"
    cpu_count = Column(Integer, nullable=True)  # Number of CPUs
    cpu_frequency = Column(Integer, nullable=True)  # MHz
    cpu_load = Column(Integer, nullable=True)  # Percentage (0-100)
    total_memory = Column(BigInteger, nullable=True)  # Total RAM in bytes
    free_memory = Column(BigInteger, nullable=True)  # Free RAM in bytes
    total_hdd_space = Column(BigInteger, nullable=True)  # Total storage in bytes
    free_hdd_space = Column(BigInteger, nullable=True)  # Free storage in bytes

    # Location
    location = Column(String(200), nullable=True)
    latitude = Column(String(20), nullable=True)
    longitude = Column(String(20), nullable=True)
    
    # Configuration
    config = Column(Text, nullable=True)  # JSON configuration
    notes = Column(Text, nullable=True)
    
    # Provisioning and API credentials (for reprovisioning)
    api_credentials_encrypted = Column(Text, nullable=True)  # Encrypted username:password for API access
    last_provisioned_at = Column(DateTime, nullable=True)  # Last successful provisioning timestamp
    provisioning_status = Column(String(50), default='pending', nullable=False)  # pending, provisioned, failed
    bootstrap_completed = Column(Boolean, default=False, nullable=False)  # True if initial bootstrap was successful

    # Polling agent fields
    agent_token = Column(String(255), nullable=True)  # Hashed per-router auth token
    agent_token_plain = Column(Text, nullable=True)  # Encrypted plain token (included in bootstrap script)
    agent_installed = Column(Boolean, default=False, nullable=False)
    agent_poll_interval = Column(Integer, default=30, nullable=False)  # seconds
    last_poll_at = Column(DateTime, nullable=True)  # Last successful poll from agent
    agent_version = Column(String(20), nullable=True)  # Agent script version on router

    # Agent-reported active hotspot + PPPoE user list (NAT-safe live data).
    # Stored as a JSON array of {username,type,address,mac,uptime} dicts; the
    # cloud cannot query the router directly, so the polling agent reports this.
    active_users_json = Column(Text, nullable=True)
    active_users_at = Column(DateTime, nullable=True)  # When the list was last reported

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="routers")
    subscriptions = relationship("Subscription", back_populates="router", cascade="all, delete-orphan")
    devices = relationship("RouterDevice", back_populates="router", cascade="all, delete-orphan")
    logs = relationship("RouterLog", back_populates="router", cascade="all, delete-orphan")
    commands = relationship("RouterCommand", back_populates="router", cascade="all, delete-orphan")
    backups = relationship("RouterBackup", back_populates="router", cascade="all, delete-orphan")

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
    router = relationship("Router", back_populates="logs")

    def __repr__(self) -> str:
        """String representation."""
        return f"<RouterLog(id={self.id}, router_id={self.router_id}, action='{self.action}')>"


class RouterBackup(Base):
    """Router configuration backup history.

    A backup is requested NAT-safely: the cloud queues an agent action that runs
    ``/system/backup/save`` on the router locally. This row records the request,
    its lifecycle (pending -> completed/failed) and metadata. The agent command
    id links the row to the queued ``router_commands`` entry so the status can be
    reconciled from the agent's report.
    """

    __tablename__ = "router_backups"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False, index=True)
    name = Column(String(150), nullable=False)  # backup file name on the router
    status = Column(String(20), default="pending", nullable=False)  # pending, completed, failed
    backup_type = Column(String(20), default="binary", nullable=False)  # binary (.backup) / export (.rsc)

    # Link to the queued agent command (so we can reconcile status on report)
    command_id = Column(String(36), nullable=True)

    # Result / metadata
    size_bytes = Column(BigInteger, nullable=True)
    message = Column(Text, nullable=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    router = relationship("Router", back_populates="backups")

    def __repr__(self) -> str:
        """String representation."""
        return f"<RouterBackup(id={self.id}, router_id={self.router_id}, status='{self.status}')>"
