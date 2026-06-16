"""Authentication API endpoints."""

from datetime import timedelta, datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_user_unified,
)
from app.core.database import get_db
from app.core.security import create_token_pair, verify_token
from app.models.user import User
from app.schemas.user import (
    TokenRefresh,
    User as UserSchema,
)
from app.modules.auth import AuthService, UserService

# NOTE: Admin authentication is migrated to the central Codevertex SSO. This
# router keeps only: /login + /refresh (local break-glass for the seeded
# superuser if SSO is ever unreachable), /logout (stateless), and /me + /sso-me
# (unified local-or-SSO identity). All other legacy local-auth endpoints
# (register, email/phone verification, password reset/change, session
# management, 2FA) were removed — the SSO IdP (auth-api) owns those. The captive
# hotspot/PPPoE end-user portal auth is separate and unaffected.

router = APIRouter()


@router.post("/login",
            summary="User Login", 
            description="Login with username and password to get access tokens. Compatible with OAuth2 password flow for Swagger UI.",
            responses={
                200: {
                    "description": "Successful login",
                    "content": {
                        "application/json": {
                            "example": {
                                "data": {
                                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                    "token_type": "bearer",
                                    "expires_in": 1800,
                                    "user": {"id": 1, "username": "admin", "email": "admin@example.com"}
                                }
                            }
                        }
                    }
                },
                401: {"description": "Invalid credentials"},
                400: {"description": "Inactive user"}
            })
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Login user and return JWT tokens wrapped in a `data` envelope including user info.
    """
    auth_service = AuthService(db)
    user = await auth_service.authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    # 2FA is handled centrally by the SSO IdP, not by this break-glass path.
    # Create tokens
    token_data = create_token_pair(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
    )
    
    # Update last login
    await auth_service.update_last_login(user.id)
    
    # Prepare user payload
    user_payload = UserSchema.model_validate(user).model_dump()

    # Compute effective permissions (role-derived + user overrides)
    permissions = []
    seen = set()
    now = datetime.utcnow()

    if getattr(user, "role_obj", None) and getattr(user.role_obj, "permissions", None):
        for p in user.role_obj.permissions:
            permissions.append({
                "id": p.id,
                "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                "resource": p.resource,
                "description": p.description,
            })
            seen.add(p.id)

    for up in getattr(user, "permission_overrides", []) or []:
        # Skip expired overrides
        if up.expires_at and up.expires_at < now:
            continue
        p = up.permission
        if not p:
            continue
        if up.is_granted:
            if p.id not in seen:
                permissions.append({
                    "id": p.id,
                    "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                    "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                    "resource": p.resource,
                    "description": p.description,
                })
                seen.add(p.id)
        else:
            # Deny => remove if present
            permissions = [pp for pp in permissions if pp.get("id") != p.id]
            if p.id in seen:
                seen.remove(p.id)

    user_payload["permissions"] = permissions

    # Include organization info for all users (except platform superuser)
    organization_info = None
    customer_portal_info = None

    if user.organization_id:
        from sqlalchemy import select
        from app.models.organization import Organization

        # Get organization details
        org_result = await db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        organization = org_result.scalar_one_or_none()

        if organization:
            organization_info = {
                "organization_id": organization.id,
                "organization_slug": organization.slug,
                "organization_name": organization.name,
            }

            # For customers, include subscription-specific portal URL
            if user.role.value == "customer":
                from app.models.subscription import Subscription, SubscriptionType

                # Get customer's active subscription type
                sub_result = await db.execute(
                    select(Subscription).where(
                        Subscription.user_id == user.id,
                        Subscription.status.in_(["active", "suspended"])
                    ).order_by(Subscription.created_at.desc()).limit(1)
                )
                subscription = sub_result.scalar_one_or_none()

                customer_portal_info = {
                    "organization_slug": organization.slug,
                    "subscription_type": subscription.subscription_type.value if subscription else "hotspot",
                    "portal_url": f"/{organization.slug}/portal/{'pppoe' if subscription and subscription.subscription_type == SubscriptionType.PPPOE else 'hotspot'}"
                }

    response_data = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "token_type": token_data["token_type"],
        "expires_in": 30 * 60,  # 30 minutes
        "user": user_payload,
    }

    # Add organization info for ISP users (isp_admin, isp_technician)
    if organization_info and user.role.value in ["isp_admin", "isp_technician"]:
        response_data["organization"] = organization_info

    # Add customer portal info for customers
    if customer_portal_info:
        response_data["customer_portal"] = customer_portal_info

    return {"data": response_data}


@router.post("/refresh")
async def refresh_token(
    token_data: TokenRefresh,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token (returns wrapped `data`)."""
    auth_service = AuthService(db)
    
    # Verify refresh token
    token_info = verify_token(token_data.refresh_token, token_type="refresh")
    if not token_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Get user
    user_service = UserService(db)
    user = await user_service.get_by_id(token_info.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    # Create new tokens
    new_token_data = create_token_pair(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
    )
    
    return {
        "data": {
            "access_token": new_token_data["access_token"],
            "refresh_token": new_token_data["refresh_token"],
            "token_type": new_token_data["token_type"],
            "expires_in": 30 * 60,
        }
    }


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """Logout (stateless).

    JWTs are stateless and SSO session logout is owned by auth-api; this endpoint
    simply acknowledges so clients can clear their locally-stored tokens.
    """
    return {"message": "Successfully logged out"}


def _collect_effective_permissions(user: User) -> list:
    """Compute a user's effective permissions (role-derived + overrides)."""
    permissions: list = []
    seen: set = set()
    now = datetime.utcnow()

    if getattr(user, "role_obj", None) and getattr(user.role_obj, "permissions", None):
        for p in user.role_obj.permissions:
            permissions.append({
                "id": p.id,
                "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                "resource": p.resource,
                "description": p.description,
            })
            seen.add(p.id)

    for up in getattr(user, "permission_overrides", []) or []:
        if up.expires_at and up.expires_at < now:
            continue
        p = up.permission
        if not p:
            continue
        if up.is_granted:
            if p.id not in seen:
                permissions.append({
                    "id": p.id,
                    "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                    "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                    "resource": p.resource,
                    "description": p.description,
                })
                seen.add(p.id)
        else:
            permissions = [pp for pp in permissions if pp.get("id") != p.id]
            if p.id in seen:
                seen.remove(p.id)

    return permissions


@router.get("/me")
async def get_current_user_info(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_unified),
):
    """Get current user information (wrapped in `data`).

    Phase 1b: now resolves via the unified dependency, so it works for BOTH
    local-JWT and SSO-authenticated users. When the request arrived via SSO,
    the payload is enriched with `global_roles` + tenant context from the JWT.
    """
    user_payload = UserSchema.model_validate(current_user).model_dump()
    user_payload["permissions"] = _collect_effective_permissions(current_user)

    # Always include the org slug/name so the UI can build the role-based
    # dashboard URL (/{slug}/dashboard) even when the SSO token didn't carry a
    # tenant_slug claim (e.g. a direct login without ?tenant=). Resolved from
    # organization_id with an explicit query — the relationship is not eager-
    # loaded on SSO-provisioned users, so a lazy access would fail under async.
    user_payload["organization_slug"] = None
    user_payload["organization_name"] = None
    if current_user.organization_id:
        from sqlalchemy import select
        from app.models.organization import Organization
        org_row = (
            await db.execute(
                select(Organization.slug, Organization.name).where(
                    Organization.id == current_user.organization_id
                )
            )
        ).first()
        if org_row:
            user_payload["organization_slug"] = org_row[0]
            user_payload["organization_name"] = org_row[1]

    # Enrich with SSO context when the request was SSO-authenticated.
    claims = getattr(request.state, "sso_claims", None)
    if claims:
        user_payload["auth_source"] = "sso"
        user_payload["global_roles"] = claims.get("roles") or []
        user_payload["tenant_id"] = claims.get("tenant_id")
        user_payload["tenant_slug"] = claims.get("tenant_slug")
        user_payload["is_platform_owner"] = bool(claims.get("is_platform_owner"))
    else:
        user_payload["auth_source"] = "local"

    return {"data": user_payload}


@router.get("/sso-me")
async def get_sso_current_user_info(
    request: Request,
    current_user: User = Depends(get_current_user_unified),
):
    """SSO-oriented identity view (wrapped in `data`).

    Returns the resolved local identity plus the global SSO context: user_id,
    email, tenant_id/slug, global_roles, the resolved ISP role, and the
    effective local-RBAC permissions. Works for SSO users (full context) and
    local users (global_roles empty, auth_source=local).
    """
    claims = getattr(request.state, "sso_claims", None) or {}
    return {
        "data": {
            "user_id": current_user.id,
            "auth_service_user_id": current_user.auth_service_user_id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "tenant_id": claims.get("tenant_id"),
            "tenant_slug": claims.get("tenant_slug"),
            "organization_id": current_user.organization_id,
            "global_roles": claims.get("roles") or [],
            "isp_role": current_user.role.value if current_user.role else None,
            "is_platform_owner": bool(claims.get("is_platform_owner")) or current_user.is_platform_owner,
            "auth_source": "sso" if claims else "local",
            "subscription": {
                "status": claims.get("sub_status"),
                "plan": claims.get("sub_plan"),
                "features": claims.get("sub_features") or [],
                "limits": claims.get("sub_limits") or {},
                "expires": claims.get("sub_expires"),
            } if claims else None,
            "permissions": _collect_effective_permissions(current_user),
        }
    }


# Legacy local-auth endpoints (email/phone verification, password reset/change,
# and session management) were removed — these are owned by the central SSO
# (auth-api) and the user-profile UI in accounts.codevertexitsolutions.com.
