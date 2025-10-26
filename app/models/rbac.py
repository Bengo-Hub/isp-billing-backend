"""RBAC (Role-Based Access Control) models."""

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
    Table,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class PermissionModule(str, PyEnum):
    """Permission module enumeration."""
    
    # Core modules
    DASHBOARD = "dashboard"
    USERS = "users"
    PACKAGES = "packages"
    ROUTERS = "routers"
    PROVISIONING = "provisioning"
    PAYMENTS = "payments"
    SMS = "sms"
    SETTINGS = "settings"
    REPORTS = "reports"
    NOTIFICATIONS = "notifications"
    
    # Advanced modules
    SYSTEM_CONFIG = "system_config"
    LICENCE_MANAGEMENT = "licence_management"
    AUDIT_LOGS = "audit_logs"
    BACKUP_RESTORE = "backup_restore"


class PermissionAction(str, PyEnum):
    """Permission action enumeration."""
    
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    MANAGE = "manage"  # Full CRUD + advanced operations


class UserRole(str, PyEnum):
    """Enhanced user role enumeration."""

    SUPERUSER = "superuser"  # ISP Software Provider/Dev
    ADMIN = "admin"          # ISP Provider Admin
    TECHNICIAN = "technician"
    CUSTOMER = "customer"


# Association table for role-permission many-to-many relationship
role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id'), primary_key=True),
)


class Role(Base):
    """Role model for RBAC."""
    
    __tablename__ = "roles"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Role information
    name = Column(String(50), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    is_system_role = Column(Boolean, default=False, nullable=False)  # System roles cannot be deleted
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")
    users = relationship("User", back_populates="role_obj")
    
    def __repr__(self) -> str:
        """String representation."""
        return f"<Role(id={self.id}, name='{self.name}')>"


class Permission(Base):
    """Permission model for RBAC."""
    
    __tablename__ = "permissions"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Permission information
    module = Column(Enum(PermissionModule), nullable=False, index=True)
    action = Column(Enum(PermissionAction), nullable=False, index=True)
    resource = Column(String(100), nullable=True)  # Specific resource within module
    description = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('module', 'action', 'resource', name='uq_permission_module_action_resource'),
    )
    
    def __repr__(self) -> str:
        """String representation."""
        return f"<Permission(id={self.id}, module='{self.module}', action='{self.action}', resource='{self.resource}')>"


class UserPermission(Base):
    """User-specific permission overrides."""
    
    __tablename__ = "user_permissions"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)
    
    # Permission override
    is_granted = Column(Boolean, default=True, nullable=False)  # True = granted, False = denied
    reason = Column(Text, nullable=True)  # Reason for override
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration
    
    # Relationships
    user = relationship("User", back_populates="permission_overrides")
    permission = relationship("Permission")
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'permission_id', name='uq_user_permission'),
    )
    
    def __repr__(self) -> str:
        """String representation."""
        return f"<UserPermission(id={self.id}, user_id={self.user_id}, permission_id={self.permission_id}, granted={self.is_granted})>"


class SystemLicence(Base):
    """System licence model for trial and subscription management."""
    
    __tablename__ = "system_licences"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Licence information
    licence_key = Column(String(255), unique=True, index=True, nullable=False)
    organization_name = Column(String(200), nullable=False)
    contact_email = Column(String(100), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    
    # Licence details
    licence_type = Column(String(50), nullable=False, default="trial")  # trial, subscription, perpetual
    is_active = Column(Boolean, default=True, nullable=False)
    max_users = Column(Integer, default=10, nullable=False)
    max_routers = Column(Integer, default=5, nullable=False)
    
    # Trial settings
    trial_days = Column(Integer, default=14, nullable=False)
    trial_started_at = Column(DateTime, nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)
    
    # Subscription settings
    subscription_started_at = Column(DateTime, nullable=True)
    subscription_expires_at = Column(DateTime, nullable=True)
    auto_renew = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self) -> str:
        """String representation."""
        return f"<SystemLicence(id={self.id}, licence_key='{self.licence_key}', type='{self.licence_type}')>"
    
    @property
    def is_trial_active(self) -> bool:
        """Check if trial is active."""
        if self.licence_type != "trial" or not self.trial_started_at:
            return False
        
        from datetime import datetime
        return datetime.utcnow() < self.trial_expires_at if self.trial_expires_at else False
    
    @property
    def days_remaining(self) -> int:
        """Get days remaining in trial."""
        if not self.is_trial_active:
            return 0
        
        from datetime import datetime
        delta = self.trial_expires_at - datetime.utcnow()
        return max(0, delta.days)
