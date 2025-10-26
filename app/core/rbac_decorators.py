"""RBAC decorators for protecting endpoints."""

from functools import wraps
from typing import List, Optional

from fastapi import HTTPException, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.rbac import PermissionModule, PermissionAction
from app.services.rbac_service import RBACService


def require_permission(
    module: PermissionModule,
    action: PermissionAction,
    resource: Optional[str] = None
):
    """Decorator to require specific permission."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract dependencies
            current_user: User = None
            db: Session = None
            
            for arg in args:
                if isinstance(arg, User):
                    current_user = arg
                elif isinstance(arg, Session):
                    db = arg
            
            for key, value in kwargs.items():
                if isinstance(value, User):
                    current_user = value
                elif isinstance(value, Session):
                    db = value
            
            if not current_user or not db:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            # Check permission
            rbac_service = RBACService(db)
            if not rbac_service.has_permission(current_user.id, module, action, resource):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required: {module.value}.{action.value}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(required_roles: List[str]):
    """Decorator to require specific role(s)."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract dependencies
            current_user: User = None
            
            for arg in args:
                if isinstance(arg, User):
                    current_user = arg
            
            for key, value in kwargs.items():
                if isinstance(value, User):
                    current_user = value
            
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            if current_user.role.value not in required_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient role. Required: {required_roles}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_superuser(func):
    """Decorator to require superuser role."""
    return require_role(["superuser"])(func)


def require_admin_or_superuser(func):
    """Decorator to require admin or superuser role."""
    return require_role(["admin", "superuser"])(func)


# Common permission decorators
def require_dashboard_access(func):
    """Require dashboard read access."""
    return require_permission(PermissionModule.DASHBOARD, PermissionAction.READ)(func)


def require_user_management(func):
    """Require user management permissions."""
    return require_permission(PermissionModule.USERS, PermissionAction.MANAGE)(func)


def require_package_management(func):
    """Require package management permissions."""
    return require_permission(PermissionModule.PACKAGES, PermissionAction.MANAGE)(func)


def require_router_management(func):
    """Require router management permissions."""
    return require_permission(PermissionModule.ROUTERS, PermissionAction.MANAGE)(func)


def require_provisioning_access(func):
    """Require provisioning management permissions."""
    return require_permission(PermissionModule.PROVISIONING, PermissionAction.MANAGE)(func)


def require_payment_access(func):
    """Require payment management permissions."""
    return require_permission(PermissionModule.PAYMENTS, PermissionAction.MANAGE)(func)


def require_sms_access(func):
    """Require SMS management permissions."""
    return require_permission(PermissionModule.SMS, PermissionAction.MANAGE)(func)


def require_settings_access(func):
    """Require settings update permissions."""
    return require_permission(PermissionModule.SETTINGS, PermissionAction.UPDATE)(func)


def require_system_config_access(func):
    """Require system configuration permissions (superuser only)."""
    return require_permission(PermissionModule.SYSTEM_CONFIG, PermissionAction.MANAGE)(func)


def require_reports_access(func):
    """Require reports management permissions."""
    return require_permission(PermissionModule.REPORTS, PermissionAction.MANAGE)(func)


def require_backup_restore_access(func):
    """Require backup/restore permissions."""
    return require_permission(PermissionModule.BACKUP_RESTORE, PermissionAction.MANAGE)(func)
