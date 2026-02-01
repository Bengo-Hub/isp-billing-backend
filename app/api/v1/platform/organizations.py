"""
Platform Owner API - Organization Management.

Endpoints for managing ISP providers (tenants).
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.api.deps_tenant import require_platform_owner
from app.models.organization import Organization, OrganizationSettings, OrganizationType, OrganizationStatus
from app.models.user import User
from app.modules.platform_billing.service import PlatformBillingService

router = APIRouter(prefix="/organizations", tags=["Platform - Organizations"])


# =========================================================================
# Schemas
# =========================================================================

class OrganizationCreate(BaseModel):
    """Schema for creating an organization."""

    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    organization_type: OrganizationType = OrganizationType.HOTSPOT
    email: str = Field(..., max_length=100)
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: str = "Kenya"
    primary_color: str = "#ec4899"
    secondary_color: Optional[str] = "#8b5cf6"
    default_currency: str = "KES"
    timezone: str = "Africa/Nairobi"
    notification_email: Optional[str] = None
    notification_phone: Optional[str] = None
    sms_sender_id: Optional[str] = None
    subscription_tier_id: Optional[int] = None
    trial_days: int = 14
    max_routers: int = 5
    max_customers: int = 100
    max_users: int = 5


class OrganizationUpdate(BaseModel):
    """Schema for updating an organization."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    portal_domain: Optional[str] = None
    portal_title: Optional[str] = None
    portal_description: Optional[str] = None
    subscription_tier_id: Optional[int] = None
    max_routers: Optional[int] = None
    max_customers: Optional[int] = None
    max_users: Optional[int] = None
    status: Optional[OrganizationStatus] = None


class OrganizationResponse(BaseModel):
    """Response schema for organization."""

    id: int
    uuid: str
    name: str
    slug: str
    organization_type: OrganizationType
    status: OrganizationStatus
    email: str
    phone: Optional[str]
    address: Optional[str]
    city: Optional[str]
    country: str
    logo_url: Optional[str]
    primary_color: str
    portal_domain: Optional[str]
    subscription_tier_id: Optional[int]
    trial_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]
    max_routers: int
    max_customers: int
    max_users: int
    total_revenue: int
    total_customers: int
    active_subscriptions: int
    is_trial: bool
    trial_days_remaining: int
    is_subscription_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrganizationListResponse(BaseModel):
    """Paginated list of organizations."""

    items: List[OrganizationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class OrganizationStats(BaseModel):
    """Organization statistics."""

    total_organizations: int
    active_organizations: int
    trial_organizations: int
    suspended_organizations: int
    pending_payment_organizations: int
    total_revenue_this_month: float
    new_organizations_this_month: int


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/", response_model=OrganizationListResponse)
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
    status: Optional[OrganizationStatus] = None,
    organization_type: Optional[OrganizationType] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    List all ISP provider organizations.

    Platform owner only.
    """
    query = select(Organization)

    if status:
        query = query.where(Organization.status == status)

    if organization_type:
        query = query.where(Organization.organization_type == organization_type)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Organization.name.ilike(search_filter)) |
            (Organization.email.ilike(search_filter)) |
            (Organization.slug.ilike(search_filter))
        )

    # Get total count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    # Apply pagination
    query = query.order_by(Organization.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    organizations = list(result.scalars().all())

    return OrganizationListResponse(
        items=[OrganizationResponse(
            **org.to_dict(),
            is_trial=org.is_trial,
            trial_days_remaining=org.trial_days_remaining,
            is_subscription_active=org.is_subscription_active,
        ) for org in organizations],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/stats", response_model=OrganizationStats)
async def get_organization_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get organization statistics.

    Platform owner only.
    """
    # Total counts by status
    result = await db.execute(
        select(Organization.status, func.count(Organization.id))
        .group_by(Organization.status)
    )
    status_counts = {row[0]: row[1] for row in result.all()}

    # New organizations this month
    first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_result = await db.execute(
        select(func.count(Organization.id))
        .where(Organization.created_at >= first_of_month)
    )
    new_this_month = new_result.scalar() or 0

    # Total revenue this month
    revenue_result = await db.execute(
        select(func.sum(Organization.total_revenue))
    )
    total_revenue = revenue_result.scalar() or 0

    return OrganizationStats(
        total_organizations=sum(status_counts.values()),
        active_organizations=status_counts.get(OrganizationStatus.ACTIVE, 0),
        trial_organizations=status_counts.get(OrganizationStatus.TRIAL, 0),
        suspended_organizations=status_counts.get(OrganizationStatus.SUSPENDED, 0),
        pending_payment_organizations=status_counts.get(OrganizationStatus.PENDING_PAYMENT, 0),
        total_revenue_this_month=float(total_revenue) / 100,  # Convert from cents
        new_organizations_this_month=new_this_month,
    )


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Create a new ISP provider organization.

    Platform owner only.
    """
    # Check if slug is unique
    existing = await db.execute(
        select(Organization).where(Organization.slug == data.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization slug already exists"
        )

    # Check if email is unique
    existing_email = await db.execute(
        select(Organization).where(Organization.email == data.email)
    )
    if existing_email.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization email already exists"
        )

    # Create organization
    from datetime import timedelta

    trial_ends_at = datetime.utcnow() + timedelta(days=data.trial_days)

    organization = Organization(
        name=data.name,
        slug=data.slug,
        organization_type=data.organization_type,
        status=OrganizationStatus.TRIAL,
        email=data.email,
        phone=data.phone,
        address=data.address,
        city=data.city,
        country=data.country,
        primary_color=data.primary_color,
        secondary_color=data.secondary_color,
        default_currency=data.default_currency,
        timezone=data.timezone,
        notification_email=data.notification_email,
        notification_phone=data.notification_phone,
        sms_sender_id=data.sms_sender_id,
        subscription_tier_id=data.subscription_tier_id,
        trial_ends_at=trial_ends_at,
        max_routers=data.max_routers,
        max_customers=data.max_customers,
        max_users=data.max_users,
        created_by=current_user.id,
    )

    db.add(organization)
    await db.commit()
    await db.refresh(organization)

    # Create default organization settings
    org_settings = OrganizationSettings(
        organization_id=organization.id,
        # MikroTik Settings
        enable_mikrotik_status_notifications=True,
        # SMS Payment Confirmations
        send_hotspot_payment_confirmation=True,
        hotspot_payment_confirmation_sms=(
            "Hello @username! You've successfully subscribed to @package_name. "
            "Username: @username, Password: @password, Expires: @expiry_date. Thank you!"
        ),
        send_pppoe_payment_confirmation=True,
        pppoe_payment_confirmation_sms=(
            "Hello @username! You've successfully subscribed to @package_name. "
            "Username: @username, Password: @password, Expires: @expiry_date. Thank you!"
        ),
        # SMS Expiry Notifications
        send_hotspot_expiry_notification=True,
        hotspot_expiry_notification_sms=(
            "Hello @username! Your @package_name subscription expired on @expiry_date. "
            "Renew now to continue enjoying our services. Paybill: @paybill, Account: @account_number"
        ),
        send_pppoe_expiry_notification=True,
        pppoe_expiry_notification_sms=(
            "Hello @username! Your @package_name subscription expired on @expiry_date. "
            "Renew now to continue enjoying our services. Paybill: @paybill, Account: @account_number"
        ),
        # SMS Expiry Reminders
        send_hotspot_expiry_reminder=True,
        hotspot_expiry_reminder_sms=(
            "Hello @username! Your @package_name subscription expires in @days_left days on @expiry_date. "
            "Renew now to avoid interruption. Paybill: @paybill, Account: @account_number"
        ),
        send_pppoe_expiry_reminder=True,
        pppoe_expiry_reminder_sms=(
            "Hello @username! Your @package_name subscription expires in @days_left days on @expiry_date. "
            "Renew now to avoid interruption. Paybill: @paybill, Account: @account_number"
        ),
        # WhatsApp Settings (disabled by default - requires subscription)
        whatsapp_enabled=False,
        whatsapp_provider=None,
        send_hotspot_payment_confirmation_whatsapp=False,
        hotspot_payment_confirmation_whatsapp=(
            "Hello @username! 👋\n\n"
            "You've successfully subscribed to *@package_name*\n\n"
            "✅ Username: @username\n"
            "🔑 Password: @password\n"
            "📅 Expires: @expiry_date\n\n"
            "Thank you for choosing us!"
        ),
        send_pppoe_payment_confirmation_whatsapp=False,
        pppoe_payment_confirmation_whatsapp=(
            "Hello @username! 👋\n\n"
            "You've successfully subscribed to *@package_name*\n\n"
            "✅ Username: @username\n"
            "🔑 Password: @password\n"
            "📅 Expires: @expiry_date\n\n"
            "Thank you for choosing us!"
        ),
        send_hotspot_expiry_notification_whatsapp=False,
        hotspot_expiry_notification_whatsapp=(
            "Hello @username! ⚠️\n\n"
            "Your *@package_name* subscription has expired.\n\n"
            "📅 Expired on: @expiry_date\n"
            "💳 Paybill: @paybill\n"
            "📋 Account: @account_number\n\n"
            "Renew now to continue enjoying our services!"
        ),
        send_pppoe_expiry_notification_whatsapp=False,
        pppoe_expiry_notification_whatsapp=(
            "Hello @username! ⚠️\n\n"
            "Your *@package_name* subscription has expired.\n\n"
            "📅 Expired on: @expiry_date\n"
            "💳 Paybill: @paybill\n"
            "📋 Account: @account_number\n\n"
            "Renew now to continue enjoying our services!"
        ),
        send_hotspot_expiry_reminder_whatsapp=False,
        hotspot_expiry_reminder_whatsapp=(
            "Hello @username! ⏰\n\n"
            "Your package expires in *@days_left days*\n\n"
            "📅 Expiry Date: @expiry_date\n"
            "💳 Paybill: @paybill\n"
            "📋 Account: @account_number\n\n"
            "Renew now to avoid interruption!"
        ),
        send_pppoe_expiry_reminder_whatsapp=False,
        pppoe_expiry_reminder_whatsapp=(
            "Hello @username! ⏰\n\n"
            "Your package expires in *@days_left days*\n\n"
            "📅 Expiry Date: @expiry_date\n"
            "💳 Paybill: @paybill\n"
            "📋 Account: @account_number\n\n"
            "Renew now to avoid interruption!"
        ),
    )
    db.add(org_settings)
    await db.commit()

    return OrganizationResponse(
        **organization.to_dict(),
        is_trial=organization.is_trial,
        trial_days_remaining=organization.trial_days_remaining,
        is_subscription_active=organization.is_subscription_active,
    )


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get an organization by ID.

    Platform owner only.
    """
    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    return OrganizationResponse(
        **organization.to_dict(),
        is_trial=organization.is_trial,
        trial_days_remaining=organization.trial_days_remaining,
        is_subscription_active=organization.is_subscription_active,
    )


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: int,
    data: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Update an organization.

    Platform owner only.
    """
    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(organization, key):
            setattr(organization, key, value)

    organization.updated_by = current_user.id

    await db.commit()
    await db.refresh(organization)

    return OrganizationResponse(
        **organization.to_dict(),
        is_trial=organization.is_trial,
        trial_days_remaining=organization.trial_days_remaining,
        is_subscription_active=organization.is_subscription_active,
    )


@router.post("/{organization_id}/suspend")
async def suspend_organization(
    organization_id: int,
    reason: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Suspend an organization.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    success = await billing_service.suspend_organization(organization_id, reason)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    return {"message": "Organization suspended"}


@router.post("/{organization_id}/reactivate")
async def reactivate_organization(
    organization_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Reactivate a suspended organization.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    success = await billing_service.reactivate_organization(organization_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reactivate organization. Subscription may not be active."
        )

    return {"message": "Organization reactivated"}


@router.get("/{organization_id}/earnings")
async def get_organization_earnings(
    organization_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get earnings for an organization.

    Platform owner only.
    """
    if not start_date:
        start_date = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if not end_date:
        end_date = datetime.utcnow()

    billing_service = PlatformBillingService(db)
    total_earnings, customer_count = await billing_service.get_organization_earnings(
        organization_id, start_date, end_date
    )

    return {
        "organization_id": organization_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_earnings": float(total_earnings),
        "customer_count": customer_count,
    }
