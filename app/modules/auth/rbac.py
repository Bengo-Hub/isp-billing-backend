"""RBAC (Role-Based Access Control) service."""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.user import User, UserRole
from app.models.rbac import (
    Role, Permission, UserPermission, PermissionModule, 
    PermissionAction, SystemLicence
)
from app.core.exceptions import PermissionDeniedError, ResourceNotFoundError


class RBACService:
    """RBAC service for managing roles, permissions, and access control."""
    
    def __init__(self, db: Session):
        self.db = db
    
    # Role Management
    def create_role(self, name: str, description: str = None, is_system_role: bool = False) -> Role:
        """Create a new role."""
        role = Role(
            name=name,
            description=description,
            is_system_role=is_system_role
        )
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role
    
    def get_role(self, role_id: int) -> Optional[Role]:
        """Get role by ID."""
        return self.db.query(Role).filter(Role.id == role_id).first()
    
    def get_role_by_name(self, name: str) -> Optional[Role]:
        """Get role by name."""
        return self.db.query(Role).filter(Role.name == name).first()
    
    def list_roles(self) -> List[Role]:
        """List all roles."""
        return self.db.query(Role).all()
    
    def update_role(self, role_id: int, **kwargs) -> Optional[Role]:
        """Update role."""
        role = self.get_role(role_id)
        if not role:
            return None
        
        for key, value in kwargs.items():
            if hasattr(role, key):
                setattr(role, key, value)
        
        self.db.commit()
        self.db.refresh(role)
        return role
    
    def delete_role(self, role_id: int) -> bool:
        """Delete role (only if not system role)."""
        role = self.get_role(role_id)
        if not role or role.is_system_role:
            return False
        
        self.db.delete(role)
        self.db.commit()
        return True
    
    # Permission Management
    def create_permission(
        self, 
        module: PermissionModule, 
        action: PermissionAction, 
        resource: str = None,
        description: str = None
    ) -> Permission:
        """Create a new permission."""
        permission = Permission(
            module=module,
            action=action,
            resource=resource,
            description=description
        )
        self.db.add(permission)
        self.db.commit()
        self.db.refresh(permission)
        return permission
    
    def get_permission(self, permission_id: int) -> Optional[Permission]:
        """Get permission by ID."""
        return self.db.query(Permission).filter(Permission.id == permission_id).first()
    
    def get_permission_by_module_action(
        self, 
        module: PermissionModule, 
        action: PermissionAction, 
        resource: str = None
    ) -> Optional[Permission]:
        """Get permission by module, action, and resource."""
        query = self.db.query(Permission).filter(
            Permission.module == module,
            Permission.action == action
        )
        
        if resource:
            query = query.filter(Permission.resource == resource)
        else:
            query = query.filter(Permission.resource.is_(None))
        
        return query.first()
    
    def list_permissions(self) -> List[Permission]:
        """List all permissions."""
        return self.db.query(Permission).all()
    
    def list_permissions_by_module(self, module: PermissionModule) -> List[Permission]:
        """List permissions by module."""
        return self.db.query(Permission).filter(Permission.module == module).all()
    
    # Role-Permission Management
    def assign_permission_to_role(self, role_id: int, permission_id: int) -> bool:
        """Assign permission to role."""
        role = self.get_role(role_id)
        permission = self.get_permission(permission_id)
        
        if not role or not permission:
            return False
        
        if permission not in role.permissions:
            role.permissions.append(permission)
            self.db.commit()
        
        return True
    
    def remove_permission_from_role(self, role_id: int, permission_id: int) -> bool:
        """Remove permission from role."""
        role = self.get_role(role_id)
        permission = self.get_permission(permission_id)
        
        if not role or not permission:
            return False
        
        if permission in role.permissions:
            role.permissions.remove(permission)
            self.db.commit()
        
        return True
    
    def get_role_permissions(self, role_id: int) -> List[Permission]:
        """Get all permissions for a role."""
        role = self.get_role(role_id)
        return role.permissions if role else []
    
    # User-Role Management
    def assign_role_to_user(self, user_id: int, role_id: int) -> bool:
        """Assign role to user."""
        user = self.db.query(User).filter(User.id == user_id).first()
        role = self.get_role(role_id)
        
        if not user or not role:
            return False
        
        user.role_obj = role
        self.db.commit()
        return True
    
    def get_user_role(self, user_id: int) -> Optional[Role]:
        """Get user's role."""
        user = self.db.query(User).filter(User.id == user_id).first()
        return user.role_obj if user else None
    
    def get_users_by_role(self, role_id: int) -> List[User]:
        """Get all users with a specific role."""
        return self.db.query(User).filter(User.role_obj.has(Role.id == role_id)).all()
    
    # User Permission Overrides
    def grant_user_permission(
        self, 
        user_id: int, 
        permission_id: int, 
        reason: str = None,
        expires_at: datetime = None
    ) -> bool:
        """Grant specific permission to user."""
        user = self.db.query(User).filter(User.id == user_id).first()
        permission = self.get_permission(permission_id)
        
        if not user or not permission:
            return False
        
        # Remove existing override if any
        existing = self.db.query(UserPermission).filter(
            UserPermission.user_id == user_id,
            UserPermission.permission_id == permission_id
        ).first()
        
        if existing:
            existing.is_granted = True
            existing.reason = reason
            existing.expires_at = expires_at
        else:
            override = UserPermission(
                user_id=user_id,
                permission_id=permission_id,
                is_granted=True,
                reason=reason,
                expires_at=expires_at
            )
            self.db.add(override)
        
        self.db.commit()
        return True
    
    def deny_user_permission(
        self, 
        user_id: int, 
        permission_id: int, 
        reason: str = None,
        expires_at: datetime = None
    ) -> bool:
        """Deny specific permission to user."""
        user = self.db.query(User).filter(User.id == user_id).first()
        permission = self.get_permission(permission_id)
        
        if not user or not permission:
            return False
        
        # Remove existing override if any
        existing = self.db.query(UserPermission).filter(
            UserPermission.user_id == user_id,
            UserPermission.permission_id == permission_id
        ).first()
        
        if existing:
            existing.is_granted = False
            existing.reason = reason
            existing.expires_at = expires_at
        else:
            override = UserPermission(
                user_id=user_id,
                permission_id=permission_id,
                is_granted=False,
                reason=reason,
                expires_at=expires_at
            )
            self.db.add(override)
        
        self.db.commit()
        return True
    
    def remove_user_permission_override(self, user_id: int, permission_id: int) -> bool:
        """Remove user permission override."""
        override = self.db.query(UserPermission).filter(
            UserPermission.user_id == user_id,
            UserPermission.permission_id == permission_id
        ).first()
        
        if not override:
            return False
        
        self.db.delete(override)
        self.db.commit()
        return True
    
    def get_user_permission_overrides(self, user_id: int) -> List[UserPermission]:
        """Get all permission overrides for a user."""
        return self.db.query(UserPermission).filter(
            UserPermission.user_id == user_id
        ).all()
    
    # Permission Checking
    def has_permission(
        self, 
        user_id: int, 
        module: PermissionModule, 
        action: PermissionAction, 
        resource: str = None
    ) -> bool:
        """Check if user has specific permission."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        # Check for user-specific permission override first
        override = self.db.query(UserPermission).join(Permission).filter(
            UserPermission.user_id == user_id,
            Permission.module == module,
            Permission.action == action,
            Permission.resource == resource if resource else None
        ).first()
        
        if override:
            # Check if override is expired
            if override.expires_at and override.expires_at < datetime.utcnow():
                # Remove expired override
                self.db.delete(override)
                self.db.commit()
            else:
                return override.is_granted
        
        # Check role permissions
        if user.role_obj:
            for permission in user.role_obj.permissions:
                if (permission.module == module and 
                    permission.action == action and 
                    permission.resource == (resource if resource else None)):
                    return True
        
        return False
    
    def get_user_permissions(self, user_id: int) -> List[Permission]:
        """Get all permissions for a user (role + overrides)."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return []
        
        permissions = set()
        
        # Add role permissions
        if user.role_obj:
            for permission in user.role_obj.permissions:
                permissions.add(permission)
        
        # Add/remove user permission overrides
        overrides = self.get_user_permission_overrides(user_id)
        for override in overrides:
            # Check if override is expired
            if override.expires_at and override.expires_at < datetime.utcnow():
                continue
            
            if override.is_granted:
                permissions.add(override.permission)
            else:
                permissions.discard(override.permission)
        
        return list(permissions)
    
    # Licence Management
    def create_system_licence(
        self,
        licence_key: str,
        organization_name: str,
        contact_email: str,
        contact_phone: str = None,
        licence_type: str = "trial",
        trial_days: int = 14,
        max_users: int = 10,
        max_routers: int = 5
    ) -> SystemLicence:
        """Create a new licence."""
        licence = SystemLicence(
            licence_key=licence_key,
            organization_name=organization_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
            licence_type=licence_type,
            trial_days=trial_days,
            max_users=max_users,
            max_routers=max_routers
        )
        
        if licence_type == "trial":
            licence.trial_started_at = datetime.utcnow()
            licence.trial_expires_at = datetime.utcnow() + timedelta(days=trial_days)
        
        self.db.add(licence)
        self.db.commit()
        self.db.refresh(licence)
        return licence
    
    def get_system_licence(self, licence_id: int) -> Optional[SystemLicence]:
        """Get licence by ID."""
        return self.db.query(SystemLicence).filter(SystemLicence.id == licence_id).first()
    
    def get_licence_by_key(self, licence_key: str) -> Optional[SystemLicence]:
        """Get licence by key."""
        return self.db.query(SystemLicence).filter(SystemLicence.licence_key == licence_key).first()
    
    def activate_licence_trial(self, licence_id: int) -> bool:
        """Activate trial for a licence."""
        licence = self.get_system_licence(licence_id)
        if not licence or licence.licence_type != "trial":
            return False
        
        licence.trial_started_at = datetime.utcnow()
        licence.trial_expires_at = datetime.utcnow() + timedelta(days=licence.trial_days)
        licence.is_active = True
        
        self.db.commit()
        return True
    
    def update_trial_days(self, licence_id: int, trial_days: int) -> bool:
        """Update trial days for a licence."""
        licence = self.get_system_licence(licence_id)
        if not licence:
            return False
        
        licence.trial_days = trial_days
        if licence.licence_type == "trial" and licence.trial_started_at:
            # Recalculate expiry if trial is active
            licence.trial_expires_at = licence.trial_started_at + timedelta(days=trial_days)
        
        self.db.commit()
        return True
    
    # System Initialization
    def initialize_system_roles_and_permissions(self):
        """Initialize system roles and permissions."""
        # Create system roles
        superuser_role = self.create_or_get_role("superuser", "ISP Software Provider/Developer", True)
        admin_role = self.create_or_get_role("admin", "ISP Provider Admin", True)
        technician_role = self.create_or_get_role("technician", "Technical Staff", True)
        customer_role = self.create_or_get_role("customer", "End Customer", True)
        
        # Create permissions for all modules
        permissions = self.create_system_permissions()
        
        # Assign permissions to roles
        self.assign_permissions_to_roles(superuser_role, admin_role, technician_role, customer_role, permissions)
        
        return {
            "superuser": superuser_role,
            "admin": admin_role,
            "technician": technician_role,
            "customer": customer_role
        }
    
    def create_or_get_role(self, name: str, description: str, is_system_role: bool = False) -> Role:
        """Create or get existing role."""
        role = self.get_role_by_name(name)
        if not role:
            role = self.create_role(name, description, is_system_role)
        return role
    
    def create_system_permissions(self) -> Dict[str, Permission]:
        """Create all system permissions."""
        permissions = {}
        
        # Define all module-action combinations
        module_actions = [
            (PermissionModule.DASHBOARD, PermissionAction.READ),
            (PermissionModule.USERS, PermissionAction.CREATE),
            (PermissionModule.USERS, PermissionAction.READ),
            (PermissionModule.USERS, PermissionAction.UPDATE),
            (PermissionModule.USERS, PermissionAction.DELETE),
            (PermissionModule.USERS, PermissionAction.MANAGE),
            (PermissionModule.PACKAGES, PermissionAction.CREATE),
            (PermissionModule.PACKAGES, PermissionAction.READ),
            (PermissionModule.PACKAGES, PermissionAction.UPDATE),
            (PermissionModule.PACKAGES, PermissionAction.DELETE),
            (PermissionModule.PACKAGES, PermissionAction.MANAGE),
            (PermissionModule.ROUTERS, PermissionAction.CREATE),
            (PermissionModule.ROUTERS, PermissionAction.READ),
            (PermissionModule.ROUTERS, PermissionAction.UPDATE),
            (PermissionModule.ROUTERS, PermissionAction.DELETE),
            (PermissionModule.ROUTERS, PermissionAction.MANAGE),
            (PermissionModule.PROVISIONING, PermissionAction.MANAGE),
            (PermissionModule.PAYMENTS, PermissionAction.READ),
            (PermissionModule.PAYMENTS, PermissionAction.MANAGE),
            (PermissionModule.SMS, PermissionAction.READ),
            (PermissionModule.SMS, PermissionAction.MANAGE),
            (PermissionModule.SETTINGS, PermissionAction.READ),
            (PermissionModule.SETTINGS, PermissionAction.UPDATE),
            (PermissionModule.REPORTS, PermissionAction.READ),
            (PermissionModule.REPORTS, PermissionAction.MANAGE),
            (PermissionModule.NOTIFICATIONS, PermissionAction.READ),
            (PermissionModule.NOTIFICATIONS, PermissionAction.MANAGE),
            (PermissionModule.SYSTEM_CONFIG, PermissionAction.MANAGE),
            (PermissionModule.LICENCE_MANAGEMENT, PermissionAction.MANAGE),
            (PermissionModule.AUDIT_LOGS, PermissionAction.READ),
            (PermissionModule.BACKUP_RESTORE, PermissionAction.MANAGE),
        ]
        
        for module, action in module_actions:
            key = f"{module.value}_{action.value}"
            permission = self.get_permission_by_module_action(module, action)
            if not permission:
                permission = self.create_permission(module, action)
            permissions[key] = permission
        
        return permissions
    
    def assign_permissions_to_roles(
        self, 
        superuser_role: Role, 
        admin_role: Role, 
        technician_role: Role, 
        customer_role: Role,
        permissions: Dict[str, Permission]
    ):
        """Assign permissions to roles based on access levels."""
        
        # Superuser gets all permissions
        for permission in permissions.values():
            if permission not in superuser_role.permissions:
                superuser_role.permissions.append(permission)
        
        # Admin gets most permissions except system config
        admin_permissions = [
            "dashboard_read", "users_manage", "packages_manage", "routers_manage",
            "provisioning_manage", "payments_manage", "sms_manage", "settings_update",
            "reports_manage", "notifications_manage"
        ]
        
        for perm_key in admin_permissions:
            if perm_key in permissions:
                permission = permissions[perm_key]
                if permission not in admin_role.permissions:
                    admin_role.permissions.append(permission)
        
        # Technician gets limited permissions
        technician_permissions = [
            "dashboard_read", "users_read", "packages_read", "routers_read",
            "provisioning_manage", "payments_read", "sms_read", "notifications_read"
        ]
        
        for perm_key in technician_permissions:
            if perm_key in permissions:
                permission = permissions[perm_key]
                if permission not in technician_role.permissions:
                    technician_role.permissions.append(permission)
        
        # Customer gets very limited permissions
        customer_permissions = ["dashboard_read", "payments_read", "notifications_read"]
        
        for perm_key in customer_permissions:
            if perm_key in permissions:
                permission = permissions[perm_key]
                if permission not in customer_role.permissions:
                    customer_role.permissions.append(permission)
        
        self.db.commit()
