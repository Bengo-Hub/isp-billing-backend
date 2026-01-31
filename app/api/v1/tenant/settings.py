"""
Tenant Settings API.

Endpoints for ISP providers to manage their organization settings.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import get_current_organization, require_isp_admin
from app.models.organization import Organization, OrganizationSettings, OrganizationType
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["Tenant - Settings"])


# =========================================================================
# Schemas
# =========================================================================

class OrganizationSettingsUpdate(BaseModel):
    """Schema for updating organization settings."""

    # General
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)

    # Branding
    logo_url: Optional[str] = Field(None, max_length=500)
    favicon_url: Optional[str] = Field(None, max_length=500)
    primary_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    secondary_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    custom_css: Optional[str] = None

    # Portal settings
    portal_title: Optional[str] = Field(None, max_length=200)
    portal_welcome_message: Optional[str] = None
    terms_and_conditions: Optional[str] = None
    privacy_policy: Optional[str] = None

    # Business settings
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    tax_rate: Optional[float] = Field(None, ge=0, le=100)
    invoice_prefix: Optional[str] = Field(None, max_length=10)
    invoice_notes: Optional[str] = None


class OrganizationDetailsUpdate(BaseModel):
    """Schema for updating organization details."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    organization_type: Optional[OrganizationType] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=500)


class OrganizationResponse(BaseModel):
    """Schema for organization response."""

    id: int
    name: str
    slug: str
    organization_type: str
    status: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: str
    currency: str
    trial_ends_at: Optional[str] = None
    subscription_status: Optional[str] = None
    max_routers: int
    max_customers: Optional[int] = None

    model_config = {"from_attributes": True}


class BrandingSettingsResponse(BaseModel):
    """Schema for branding settings response."""

    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: str
    secondary_color: Optional[str] = None
    custom_css: Optional[str] = None
    portal_title: Optional[str] = None
    portal_welcome_message: Optional[str] = None


class BusinessSettingsResponse(BaseModel):
    """Schema for business settings response."""

    currency: str
    tax_rate: float
    invoice_prefix: Optional[str] = None
    invoice_notes: Optional[str] = None
    terms_and_conditions: Optional[str] = None
    privacy_policy: Optional[str] = None


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/organization", response_model=OrganizationResponse)
async def get_organization_details(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get organization details.

    ISP Admin only.
    """
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        organization_type=organization.organization_type.value,
        status=organization.status.value,
        email=organization.email,
        phone=organization.phone,
        address=organization.address,
        logo_url=organization.logo_url,
        primary_color=organization.primary_color,
        currency=organization.currency,
        trial_ends_at=organization.trial_ends_at.isoformat() if organization.trial_ends_at else None,
        subscription_status=organization.subscription_status,
        max_routers=organization.max_routers,
        max_customers=organization.max_customers,
    )


@router.patch("/organization", response_model=OrganizationResponse)
async def update_organization_details(
    data: OrganizationDetailsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update organization details.

    ISP Admin only.
    """
    if data.name is not None:
        organization.name = data.name
    if data.organization_type is not None:
        organization.organization_type = data.organization_type
    if data.email is not None:
        organization.email = data.email
    if data.phone is not None:
        organization.phone = data.phone
    if data.address is not None:
        organization.address = data.address

    await db.commit()
    await db.refresh(organization)

    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        organization_type=organization.organization_type.value,
        status=organization.status.value,
        email=organization.email,
        phone=organization.phone,
        address=organization.address,
        logo_url=organization.logo_url,
        primary_color=organization.primary_color,
        currency=organization.currency,
        trial_ends_at=organization.trial_ends_at.isoformat() if organization.trial_ends_at else None,
        subscription_status=organization.subscription_status,
        max_routers=organization.max_routers,
        max_customers=organization.max_customers,
    )


@router.get("/branding", response_model=BrandingSettingsResponse)
async def get_branding_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get branding settings.

    ISP Admin only.
    """
    # Get or create settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    return BrandingSettingsResponse(
        logo_url=organization.logo_url,
        favicon_url=settings.favicon_url if settings else None,
        primary_color=organization.primary_color,
        secondary_color=settings.secondary_color if settings else None,
        custom_css=settings.custom_css if settings else None,
        portal_title=settings.portal_title if settings else organization.name,
        portal_welcome_message=settings.portal_welcome_message if settings else None,
    )


@router.patch("/branding", response_model=BrandingSettingsResponse)
async def update_branding_settings(
    logo_url: Optional[str] = None,
    favicon_url: Optional[str] = None,
    primary_color: Optional[str] = None,
    secondary_color: Optional[str] = None,
    custom_css: Optional[str] = None,
    portal_title: Optional[str] = None,
    portal_welcome_message: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update branding settings.

    ISP Admin only.
    """
    # Update organization fields
    if logo_url is not None:
        organization.logo_url = logo_url
    if primary_color is not None:
        organization.primary_color = primary_color

    # Get or create settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = OrganizationSettings(organization_id=organization.id)
        db.add(settings)

    if favicon_url is not None:
        settings.favicon_url = favicon_url
    if secondary_color is not None:
        settings.secondary_color = secondary_color
    if custom_css is not None:
        settings.custom_css = custom_css
    if portal_title is not None:
        settings.portal_title = portal_title
    if portal_welcome_message is not None:
        settings.portal_welcome_message = portal_welcome_message

    await db.commit()
    await db.refresh(organization)
    await db.refresh(settings)

    return BrandingSettingsResponse(
        logo_url=organization.logo_url,
        favicon_url=settings.favicon_url,
        primary_color=organization.primary_color,
        secondary_color=settings.secondary_color,
        custom_css=settings.custom_css,
        portal_title=settings.portal_title,
        portal_welcome_message=settings.portal_welcome_message,
    )


@router.get("/business", response_model=BusinessSettingsResponse)
async def get_business_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get business settings.

    ISP Admin only.
    """
    # Get settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    return BusinessSettingsResponse(
        currency=organization.currency,
        tax_rate=float(settings.tax_rate) if settings and settings.tax_rate else 0.0,
        invoice_prefix=settings.invoice_prefix if settings else None,
        invoice_notes=settings.invoice_notes if settings else None,
        terms_and_conditions=settings.terms_and_conditions if settings else None,
        privacy_policy=settings.privacy_policy if settings else None,
    )


@router.patch("/business", response_model=BusinessSettingsResponse)
async def update_business_settings(
    currency: Optional[str] = None,
    tax_rate: Optional[float] = None,
    invoice_prefix: Optional[str] = None,
    invoice_notes: Optional[str] = None,
    terms_and_conditions: Optional[str] = None,
    privacy_policy: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update business settings.

    ISP Admin only.
    """
    # Update organization fields
    if currency is not None:
        organization.currency = currency

    # Get or create settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = OrganizationSettings(organization_id=organization.id)
        db.add(settings)

    if tax_rate is not None:
        settings.tax_rate = tax_rate
    if invoice_prefix is not None:
        settings.invoice_prefix = invoice_prefix
    if invoice_notes is not None:
        settings.invoice_notes = invoice_notes
    if terms_and_conditions is not None:
        settings.terms_and_conditions = terms_and_conditions
    if privacy_policy is not None:
        settings.privacy_policy = privacy_policy

    await db.commit()
    await db.refresh(organization)
    await db.refresh(settings)

    return BusinessSettingsResponse(
        currency=organization.currency,
        tax_rate=float(settings.tax_rate) if settings.tax_rate else 0.0,
        invoice_prefix=settings.invoice_prefix,
        invoice_notes=settings.invoice_notes,
        terms_and_conditions=settings.terms_and_conditions,
        privacy_policy=settings.privacy_policy,
    )


@router.get("/subscription")
async def get_subscription_details(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get subscription details for the organization.

    ISP Admin only.
    """
    from app.models.platform_billing import PlatformSubscriptionTier

    tier = None
    if organization.subscription_tier_id:
        result = await db.execute(
            select(PlatformSubscriptionTier).where(
                PlatformSubscriptionTier.id == organization.subscription_tier_id
            )
        )
        tier = result.scalar_one_or_none()

    return {
        "subscription_status": organization.subscription_status,
        "trial_ends_at": organization.trial_ends_at.isoformat() if organization.trial_ends_at else None,
        "subscription_expires_at": organization.subscription_expires_at.isoformat() if organization.subscription_expires_at else None,
        "is_subscription_active": organization.is_subscription_active,
        "days_remaining": organization.subscription_days_remaining,
        "current_tier": {
            "id": tier.id,
            "name": tier.name,
            "description": tier.description,
            "base_monthly_fee": float(tier.base_monthly_fee) if tier.base_monthly_fee else None,
            "max_routers": tier.max_routers,
            "max_customers": tier.max_customers,
            "features": tier.features,
        } if tier else None,
        "limits": {
            "max_routers": organization.max_routers,
            "max_customers": organization.max_customers,
            "max_staff_users": organization.max_staff_users,
        },
    }


# =========================================================================
# Hotspot Settings
# =========================================================================

class HotspotSettingsResponse(BaseModel):
    """Schema for hotspot settings response."""

    username_prefix: str
    hotspot_template: str
    prune_inactive_users_days: int
    redirect_url: str
    voucher_format: str
    voucher_length: int
    show_packages_on_portal: bool
    allow_guest_purchases: bool
    session_timeout_minutes: int
    auto_disconnect_expired: bool


class HotspotSettingsUpdate(BaseModel):
    """Schema for updating hotspot settings."""

    username_prefix: Optional[str] = Field(None, min_length=1, max_length=10)
    hotspot_template: Optional[str] = Field(None, max_length=50)
    prune_inactive_users_days: Optional[int] = Field(None, ge=1, le=365)
    redirect_url: Optional[str] = Field(None, max_length=500)
    voucher_format: Optional[str] = Field(None, max_length=50)
    voucher_length: Optional[int] = Field(None, ge=4, le=20)
    show_packages_on_portal: Optional[bool] = None
    allow_guest_purchases: Optional[bool] = None
    session_timeout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    auto_disconnect_expired: Optional[bool] = None


@router.get("/hotspot", response_model=HotspotSettingsResponse)
async def get_hotspot_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get hotspot settings.

    ISP Admin only.
    """
    # Get or create settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings
        settings = OrganizationSettings(organization_id=organization.id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return HotspotSettingsResponse(
        username_prefix=settings.hotspot_username_prefix,
        hotspot_template=settings.hotspot_template,
        prune_inactive_users_days=settings.prune_inactive_users_days,
        redirect_url=settings.hotspot_redirect_url,
        voucher_format=settings.voucher_format,
        voucher_length=settings.voucher_length,
        show_packages_on_portal=settings.show_packages_on_portal,
        allow_guest_purchases=settings.allow_guest_purchases,
        session_timeout_minutes=settings.session_timeout_minutes,
        auto_disconnect_expired=settings.auto_disconnect_expired,
    )


@router.patch("/hotspot", response_model=HotspotSettingsResponse)
async def update_hotspot_settings(
    data: HotspotSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update hotspot settings.

    ISP Admin only.
    """
    # Get or create settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = OrganizationSettings(organization_id=organization.id)
        db.add(settings)

    # Update fields
    if data.username_prefix is not None:
        settings.hotspot_username_prefix = data.username_prefix
    if data.hotspot_template is not None:
        settings.hotspot_template = data.hotspot_template
    if data.prune_inactive_users_days is not None:
        settings.prune_inactive_users_days = data.prune_inactive_users_days
    if data.redirect_url is not None:
        settings.hotspot_redirect_url = data.redirect_url
    if data.voucher_format is not None:
        settings.voucher_format = data.voucher_format
    if data.voucher_length is not None:
        settings.voucher_length = data.voucher_length
    if data.show_packages_on_portal is not None:
        settings.show_packages_on_portal = data.show_packages_on_portal
    if data.allow_guest_purchases is not None:
        settings.allow_guest_purchases = data.allow_guest_purchases
    if data.session_timeout_minutes is not None:
        settings.session_timeout_minutes = data.session_timeout_minutes
    if data.auto_disconnect_expired is not None:
        settings.auto_disconnect_expired = data.auto_disconnect_expired

    await db.commit()
    await db.refresh(settings)

    return HotspotSettingsResponse(
        username_prefix=settings.hotspot_username_prefix,
        hotspot_template=settings.hotspot_template,
        prune_inactive_users_days=settings.prune_inactive_users_days,
        redirect_url=settings.hotspot_redirect_url,
        voucher_format=settings.voucher_format,
        voucher_length=settings.voucher_length,
        show_packages_on_portal=settings.show_packages_on_portal,
        allow_guest_purchases=settings.allow_guest_purchases,
        session_timeout_minutes=settings.session_timeout_minutes,
        auto_disconnect_expired=settings.auto_disconnect_expired,
    )


# =========================================================================
# PPPoE Settings
# =========================================================================

class PPPoESettingsResponse(BaseModel):
    """Schema for PPPoE settings response."""

    require_username_approval: bool
    allow_self_registration: bool
    session_timeout_minutes: int
    auto_disconnect_expired: bool


class PPPoESettingsUpdate(BaseModel):
    """Schema for updating PPPoE settings."""

    require_username_approval: Optional[bool] = None
    allow_self_registration: Optional[bool] = None
    session_timeout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    auto_disconnect_expired: Optional[bool] = None


@router.get("/pppoe", response_model=PPPoESettingsResponse)
async def get_pppoe_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get PPPoE settings.

    ISP Admin only.
    """
    # Get or create settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = OrganizationSettings(organization_id=organization.id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return PPPoESettingsResponse(
        require_username_approval=settings.require_username_approval,
        allow_self_registration=settings.allow_self_registration,
        session_timeout_minutes=settings.session_timeout_minutes,
        auto_disconnect_expired=settings.auto_disconnect_expired,
    )


@router.patch("/pppoe", response_model=PPPoESettingsResponse)
async def update_pppoe_settings(
    data: PPPoESettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update PPPoE settings.

    ISP Admin only.
    """
    # Get or create settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = OrganizationSettings(organization_id=organization.id)
        db.add(settings)

    # Update fields
    if data.require_username_approval is not None:
        settings.require_username_approval = data.require_username_approval
    if data.allow_self_registration is not None:
        settings.allow_self_registration = data.allow_self_registration
    if data.session_timeout_minutes is not None:
        settings.session_timeout_minutes = data.session_timeout_minutes
    if data.auto_disconnect_expired is not None:
        settings.auto_disconnect_expired = data.auto_disconnect_expired

    await db.commit()
    await db.refresh(settings)

    return PPPoESettingsResponse(
        require_username_approval=settings.require_username_approval,
        allow_self_registration=settings.allow_self_registration,
        session_timeout_minutes=settings.session_timeout_minutes,
        auto_disconnect_expired=settings.auto_disconnect_expired,
    )
