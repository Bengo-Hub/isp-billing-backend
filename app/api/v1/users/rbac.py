"""RBAC (Role-Based Access Control) API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.rbac_decorators import require_superuser, require_admin_or_superuser
from app.models.user import User
from app.models.rbac import Role, Permission, UserPermission, SystemLicence
from app.modules.auth import RBACService
from app.schemas.rbac import (
    RoleCreate, RoleUpdate, RoleResponse,
    PermissionResponse, UserPermissionCreate, UserPermissionResponse,
    LicenceCreate, LicenceUpdate, LicenceResponse
)

router = APIRouter()


# Role Management
@router.get("/roles", response_model=List[RoleResponse])
@require_admin_or_superuser
async def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all roles."""
    rbac_service = RBACService(db)
    roles = rbac_service.list_roles()
    return roles


@router.get("/roles/{role_id}", response_model=RoleResponse)
@require_admin_or_superuser
async def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get role by ID."""
    rbac_service = RBACService(db)
    role = rbac_service.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.post("/roles", response_model=RoleResponse)
@require_superuser
async def create_role(
    role_data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new role."""
    rbac_service = RBACService(db)
    role = rbac_service.create_role(
        name=role_data.name,
        description=role_data.description,
        is_system_role=role_data.is_system_role
    )
    return role


@router.put("/roles/{role_id}", response_model=RoleResponse)
@require_superuser
async def update_role(
    role_id: int,
    role_data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update role."""
    rbac_service = RBACService(db)
    role = rbac_service.update_role(role_id, **role_data.dict(exclude_unset=True))
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.delete("/roles/{role_id}")
@require_superuser
async def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete role."""
    rbac_service = RBACService(db)
    success = rbac_service.delete_role(role_id)
    if not success:
        raise HTTPException(status_code=404, detail="Role not found or cannot be deleted")
    return {"message": "Role deleted successfully"}


# Permission Management
@router.get("/permissions", response_model=List[PermissionResponse])
@require_admin_or_superuser
async def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all permissions."""
    rbac_service = RBACService(db)
    permissions = rbac_service.list_permissions()
    return permissions


@router.get("/permissions/by-module/{module}", response_model=List[PermissionResponse])
@require_admin_or_superuser
async def list_permissions_by_module(
    module: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List permissions by module."""
    rbac_service = RBACService(db)
    permissions = rbac_service.list_permissions_by_module(module)
    return permissions


# Role-Permission Management
@router.post("/roles/{role_id}/permissions/{permission_id}")
@require_superuser
async def assign_permission_to_role(
    role_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Assign permission to role."""
    rbac_service = RBACService(db)
    success = rbac_service.assign_permission_to_role(role_id, permission_id)
    if not success:
        raise HTTPException(status_code=404, detail="Role or permission not found")
    return {"message": "Permission assigned to role successfully"}


@router.delete("/roles/{role_id}/permissions/{permission_id}")
@require_superuser
async def remove_permission_from_role(
    role_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove permission from role."""
    rbac_service = RBACService(db)
    success = rbac_service.remove_permission_from_role(role_id, permission_id)
    if not success:
        raise HTTPException(status_code=404, detail="Role or permission not found")
    return {"message": "Permission removed from role successfully"}


@router.get("/roles/{role_id}/permissions", response_model=List[PermissionResponse])
@require_admin_or_superuser
async def get_role_permissions(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all permissions for a role."""
    rbac_service = RBACService(db)
    permissions = rbac_service.get_role_permissions(role_id)
    return permissions


# User-Role Management
@router.post("/users/{user_id}/roles/{role_id}")
@require_superuser
async def assign_role_to_user(
    user_id: int,
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Assign role to user."""
    rbac_service = RBACService(db)
    success = rbac_service.assign_role_to_user(user_id, role_id)
    if not success:
        raise HTTPException(status_code=404, detail="User or role not found")
    return {"message": "Role assigned to user successfully"}


@router.get("/users/{user_id}/role", response_model=RoleResponse)
@require_admin_or_superuser
async def get_user_role(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user's role."""
    rbac_service = RBACService(db)
    role = rbac_service.get_user_role(user_id)
    if not role:
        raise HTTPException(status_code=404, detail="User or role not found")
    return role


# User Permission Overrides
@router.post("/users/{user_id}/permissions/{permission_id}/grant")
@require_superuser
async def grant_user_permission(
    user_id: int,
    permission_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Grant specific permission to user."""
    rbac_service = RBACService(db)
    success = rbac_service.grant_user_permission(user_id, permission_id, reason)
    if not success:
        raise HTTPException(status_code=404, detail="User or permission not found")
    return {"message": "Permission granted to user successfully"}


@router.post("/users/{user_id}/permissions/{permission_id}/deny")
@require_superuser
async def deny_user_permission(
    user_id: int,
    permission_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deny specific permission to user."""
    rbac_service = RBACService(db)
    success = rbac_service.deny_user_permission(user_id, permission_id, reason)
    if not success:
        raise HTTPException(status_code=404, detail="User or permission not found")
    return {"message": "Permission denied to user successfully"}


@router.delete("/users/{user_id}/permissions/{permission_id}")
@require_superuser
async def remove_user_permission_override(
    user_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove user permission override."""
    rbac_service = RBACService(db)
    success = rbac_service.remove_user_permission_override(user_id, permission_id)
    if not success:
        raise HTTPException(status_code=404, detail="User permission override not found")
    return {"message": "User permission override removed successfully"}


@router.get("/users/{user_id}/permissions", response_model=List[PermissionResponse])
@require_admin_or_superuser
async def get_user_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all permissions for a user."""
    rbac_service = RBACService(db)
    permissions = rbac_service.get_user_permissions(user_id)
    return permissions


# Permission Checking
@router.get("/check-permission")
async def check_permission(
    module: str,
    action: str,
    resource: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check if current user has specific permission."""
    rbac_service = RBACService(db)
    has_permission = rbac_service.has_permission(
        current_user.id, module, action, resource
    )
    return {"has_permission": has_permission}


# Licence Management
@router.get("/licences", response_model=List[LicenceResponse])
@require_superuser
async def list_licences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all licences."""
    rbac_service = RBACService(db)
    licences = db.query(SystemLicence).all()
    return licences


@router.get("/licences/{licence_id}", response_model=LicenceResponse)
@require_superuser
async def get_licence(
    licence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get licence by ID."""
    rbac_service = RBACService(db)
    licence = rbac_service.get_licence(licence_id)
    if not licence:
        raise HTTPException(status_code=404, detail="Licence not found")
    return licence


@router.post("/licences", response_model=LicenceResponse)
@require_superuser
async def create_licence(
    licence_data: LicenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new licence."""
    rbac_service = RBACService(db)
    licence = rbac_service.create_licence(
        licence_key=licence_data.licence_key,
        organization_name=licence_data.organization_name,
        contact_email=licence_data.contact_email,
        contact_phone=licence_data.contact_phone,
        licence_type=licence_data.licence_type,
        trial_days=licence_data.trial_days,
        max_users=licence_data.max_users,
        max_routers=licence_data.max_routers
    )
    return licence


@router.put("/licences/{licence_id}", response_model=LicenceResponse)
@require_superuser
async def update_licence(
    licence_id: int,
    licence_data: LicenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update licence."""
    rbac_service = RBACService(db)
    licence = rbac_service.get_licence(licence_id)
    if not licence:
        raise HTTPException(status_code=404, detail="Licence not found")
    
    for key, value in licence_data.dict(exclude_unset=True).items():
        setattr(licence, key, value)
    
    db.commit()
    db.refresh(licence)
    return licence


@router.post("/licences/{licence_id}/activate-trial")
@require_superuser
async def activate_licence_trial(
    licence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Activate trial for a licence."""
    rbac_service = RBACService(db)
    success = rbac_service.activate_licence_trial(licence_id)
    if not success:
        raise HTTPException(status_code=404, detail="Licence not found or not a trial licence")
    return {"message": "Trial activated successfully"}


@router.put("/licences/{licence_id}/trial-days")
@require_superuser
async def update_trial_days(
    licence_id: int,
    trial_days: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update trial days for a licence."""
    rbac_service = RBACService(db)
    success = rbac_service.update_trial_days(licence_id, trial_days)
    if not success:
        raise HTTPException(status_code=404, detail="Licence not found")
    return {"message": "Trial days updated successfully"}
