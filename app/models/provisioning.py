"""Device provisioning models for MikroTik router setup and configuration."""

import json
from datetime import datetime
from enum import Enum as PyEnum
from typing import Dict, Any, Optional, List

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    Float,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ProvisioningStatus(str, PyEnum):
    """Provisioning session status enumeration."""
    
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ProvisioningStep(str, PyEnum):
    """Provisioning step enumeration."""
    
    CONNECTION = "connection"  # Step 1: Device connection and verification
    CONFIGURATION = "configuration"  # Step 2: Basic device configuration
    SERVICE_SETUP = "service_setup"  # Step 3: Service configuration (PPPoE/Hotspot)


class ServiceType(str, PyEnum):
    """Service type enumeration for provisioning."""
    
    PPPOE_SERVER = "pppoe_server"
    HOTSPOT = "hotspot"
    BOTH = "both"
    BRIDGE = "bridge"


class ProvisioningPriority(str, PyEnum):
    """Provisioning priority enumeration."""
    
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ProvisioningSession(Base):
    """Provisioning session model for tracking device setup progress."""

    __tablename__ = "provisioning_sessions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Session identification
    session_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # Who initiated
    
    # Session status and progress
    status = Column(Enum(ProvisioningStatus), default=ProvisioningStatus.PENDING, nullable=False)
    current_step = Column(Enum(ProvisioningStep), default=ProvisioningStep.CONNECTION, nullable=False)
    progress_percentage = Column(Float, default=0.0, nullable=False)
    
    # Configuration data
    service_type = Column(Enum(ServiceType), nullable=True)
    configuration = Column(JSON, nullable=True)  # Stores all configuration parameters
    
    # Timing and scheduling
    priority = Column(Enum(ProvisioningPriority), default=ProvisioningPriority.NORMAL, nullable=False)
    scheduled_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    timeout_at = Column(DateTime, nullable=True)
    
    # Result and error tracking
    success = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)
    rollback_required = Column(Boolean, default=False, nullable=False)
    rollback_completed = Column(Boolean, default=False, nullable=False)
    
    # Metadata
    ip_address = Column(String(45), nullable=True)  # Client IP
    user_agent = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    router = relationship("Router", backref="provisioning_sessions")
    user = relationship("User", backref="provisioning_sessions")
    steps = relationship("ProvisioningStepLog", back_populates="session", cascade="all, delete-orphan")
    commands = relationship("ProvisioningCommand", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """String representation."""
        return f"<ProvisioningSession(id={self.id}, session_id='{self.session_id}', status='{self.status}')>"

    def get_configuration(self) -> Dict[str, Any]:
        """Get configuration as dictionary."""
        return self.configuration or {}

    def set_configuration(self, config: Dict[str, Any]) -> None:
        """Set configuration from dictionary."""
        self.configuration = config

    def add_config_item(self, key: str, value: Any) -> None:
        """Add or update a configuration item."""
        if self.configuration is None:
            self.configuration = {}
        self.configuration[key] = value

    def get_config_item(self, key: str, default: Any = None) -> Any:
        """Get a configuration item."""
        if self.configuration is None:
            return default
        return self.configuration.get(key, default)


class ProvisioningStepLog(Base):
    """Provisioning step execution log."""

    __tablename__ = "provisioning_step_logs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    session_id = Column(Integer, ForeignKey("provisioning_sessions.id"), nullable=False)
    step = Column(Enum(ProvisioningStep), nullable=False)
    step_order = Column(Integer, nullable=False)  # Order within session
    
    # Step execution details
    status = Column(Enum(ProvisioningStatus), default=ProvisioningStatus.PENDING, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Step data and results
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_details = Column(Text, nullable=True)
    
    # Progress tracking
    progress_percentage = Column(Float, default=0.0, nullable=False)
    sub_steps_total = Column(Integer, default=1, nullable=False)
    sub_steps_completed = Column(Integer, default=0, nullable=False)
    
    # Metadata
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    session = relationship("ProvisioningSession", back_populates="steps")

    def __repr__(self) -> str:
        """String representation."""
        return f"<ProvisioningStepLog(id={self.id}, step='{self.step}', status='{self.status}')>"


class ProvisioningCommand(Base):
    """MikroTik commands executed during provisioning."""

    __tablename__ = "provisioning_commands"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    session_id = Column(Integer, ForeignKey("provisioning_sessions.id"), nullable=False)
    step_log_id = Column(Integer, ForeignKey("provisioning_step_logs.id"), nullable=True)
    
    # Command details
    command_type = Column(String(50), nullable=False)  # script, api_call, config_set
    command = Column(Text, nullable=False)  # The actual command
    description = Column(String(200), nullable=True)
    execution_order = Column(Integer, nullable=False)
    
    # Execution details
    status = Column(Enum(ProvisioningStatus), default=ProvisioningStatus.PENDING, nullable=False)
    executed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Results
    success = Column(Boolean, default=False, nullable=False)
    output = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Rollback information
    rollback_command = Column(Text, nullable=True)
    rollback_executed = Column(Boolean, default=False, nullable=False)
    
    # Metadata
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    is_critical = Column(Boolean, default=True, nullable=False)  # Failure stops provisioning
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    session = relationship("ProvisioningSession", back_populates="commands")
    step_log = relationship("ProvisioningStepLog", backref="commands")

    def __repr__(self) -> str:
        """String representation."""
        return f"<ProvisioningCommand(id={self.id}, type='{self.command_type}', status='{self.status}')>"


class ProvisioningTemplate(Base):
    """Provisioning templates for different router configurations."""

    __tablename__ = "provisioning_templates"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Template identification
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String(20), default="1.0", nullable=False)
    
    # Template configuration
    service_type = Column(Enum(ServiceType), nullable=False)
    router_model = Column(String(50), nullable=True)  # Specific router model
    min_routeros_version = Column(String(20), nullable=True)
    
    # Template data
    configuration_schema = Column(JSON, nullable=False)  # JSON schema for validation
    default_configuration = Column(JSON, nullable=False)  # Default config values
    command_templates = Column(JSON, nullable=False)  # Command templates
    
    # Template metadata
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Usage statistics
    usage_count = Column(Integer, default=0, nullable=False)
    success_rate = Column(Float, default=0.0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    creator = relationship("User", backref="provisioning_templates")

    # Constraints
    __table_args__ = (
        UniqueConstraint('name', 'version', name='uq_template_name_version'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<ProvisioningTemplate(id={self.id}, name='{self.name}', version='{self.version}')>"

    def get_configuration_schema(self) -> Dict[str, Any]:
        """Get configuration schema as dictionary."""
        return self.configuration_schema or {}

    def get_default_configuration(self) -> Dict[str, Any]:
        """Get default configuration as dictionary."""
        return self.default_configuration or {}

    def get_command_templates(self) -> Dict[str, Any]:
        """Get command templates as dictionary."""
        return self.command_templates or {}


class RouterConfiguration(Base):
    """Router configuration snapshots and history."""

    __tablename__ = "router_configurations"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("provisioning_sessions.id"), nullable=True)
    
    # Configuration details
    configuration_type = Column(String(50), nullable=False)  # initial, backup, update
    configuration_name = Column(String(100), nullable=True)
    configuration_data = Column(JSON, nullable=False)
    
    # Configuration metadata
    is_active = Column(Boolean, default=True, nullable=False)
    is_backup = Column(Boolean, default=False, nullable=False)
    checksum = Column(String(64), nullable=True)  # SHA256 of configuration
    
    # Applied configuration tracking
    applied_at = Column(DateTime, nullable=True)
    applied_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rollback_available = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    router = relationship("Router", backref="configurations")
    session = relationship("ProvisioningSession", backref="configurations")
    applied_by_user = relationship("User", backref="applied_configurations")

    def __repr__(self) -> str:
        """String representation."""
        return f"<RouterConfiguration(id={self.id}, router_id={self.router_id}, type='{self.configuration_type}')>"

    def get_configuration_data(self) -> Dict[str, Any]:
        """Get configuration data as dictionary."""
        return self.configuration_data or {}
