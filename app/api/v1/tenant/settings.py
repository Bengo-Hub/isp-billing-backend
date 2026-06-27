"""
Tenant Settings API.

Endpoints for ISP providers to manage their organization settings.
"""

from datetime import datetime
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
    # IANA timezone name (e.g. Africa/Nairobi). Pushed to routers via NTP/clock
    # sync so device timestamps match the tenant's local time.
    timezone: Optional[str] = Field(None, max_length=64)


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
    timezone: str = "Africa/Nairobi"
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


class BrandingSettingsUpdate(BaseModel):
    """Schema for updating branding settings (JSON body)."""

    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
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


class BusinessSettingsUpdate(BaseModel):
    """Schema for updating business settings (JSON body)."""

    currency: Optional[str] = None
    tax_rate: Optional[float] = None
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
        timezone=organization.timezone,
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
    if data.timezone is not None:
        organization.timezone = data.timezone

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
        timezone=organization.timezone,
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
    # All branding fields live on the Organization model (logo_url / favicon_url /
    # primary_color / secondary_color / portal_title / portal_description). The
    # OrganizationSettings table has NO branding columns, so reading them off it
    # raised AttributeError and 500'd. custom_css has no backing column today, so
    # it is not persisted (always None).
    return BrandingSettingsResponse(
        logo_url=organization.logo_url,
        favicon_url=organization.favicon_url,
        primary_color=organization.primary_color,
        secondary_color=organization.secondary_color,
        custom_css=None,
        portal_title=organization.portal_title or organization.name,
        portal_welcome_message=organization.portal_description,
    )


@router.patch("/branding", response_model=BrandingSettingsResponse)
async def update_branding_settings(
    data: BrandingSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update branding settings.

    ISP Admin only.
    """
    # All branding fields live on the Organization model (the captive portal
    # config reads them). OrganizationSettings has NO branding columns — writing
    # them there raised AttributeError and 500'd. custom_css has no backing column
    # today, so it is accepted but not persisted (reported in the fix notes).
    if data.logo_url is not None:
        organization.logo_url = data.logo_url
    if data.primary_color is not None:
        organization.primary_color = data.primary_color
    if data.favicon_url is not None:
        organization.favicon_url = data.favicon_url
    if data.secondary_color is not None:
        organization.secondary_color = data.secondary_color
    if data.portal_title is not None:
        organization.portal_title = data.portal_title
    if data.portal_welcome_message is not None:
        organization.portal_description = data.portal_welcome_message

    await db.commit()
    await db.refresh(organization)

    return BrandingSettingsResponse(
        logo_url=organization.logo_url,
        favicon_url=organization.favicon_url,
        primary_color=organization.primary_color,
        secondary_color=organization.secondary_color,
        custom_css=None,
        portal_title=organization.portal_title or organization.name,
        portal_welcome_message=organization.portal_description,
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
    data: BusinessSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update business settings.

    ISP Admin only.
    """
    # Update organization fields
    if data.currency is not None:
        organization.currency = data.currency

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

    if data.tax_rate is not None:
        settings.tax_rate = data.tax_rate
    if data.invoice_prefix is not None:
        settings.invoice_prefix = data.invoice_prefix
    if data.invoice_notes is not None:
        settings.invoice_notes = data.invoice_notes
    if data.terms_and_conditions is not None:
        settings.terms_and_conditions = data.terms_and_conditions
    if data.privacy_policy is not None:
        settings.privacy_policy = data.privacy_policy

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
    # Plan/tier is owned by subscriptions-api now (the UI reads it via the
    # subscriptions service / link-out). We return only the local subscription
    # status + limits snapshot here.
    return {
        "subscription_status": organization.subscription_status,
        "trial_ends_at": organization.trial_ends_at.isoformat() if organization.trial_ends_at else None,
        "subscription_expires_at": organization.subscription_expires_at.isoformat() if organization.subscription_expires_at else None,
        "is_subscription_active": organization.is_subscription_active,
        "days_remaining": organization.subscription_days_remaining,
        "current_tier": None,
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
    # Churn window for duration-less accounts (system default 14).
    auto_suspend_days: int


class PPPoESettingsUpdate(BaseModel):
    """Schema for updating PPPoE settings."""

    require_username_approval: Optional[bool] = None
    allow_self_registration: Optional[bool] = None
    session_timeout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    auto_disconnect_expired: Optional[bool] = None
    # Days after which duration-less hotspot/PPPoE accounts are suspended.
    auto_suspend_days: Optional[int] = Field(None, ge=1, le=365)


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
        auto_suspend_days=settings.auto_suspend_days,
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
    if data.auto_suspend_days is not None:
        settings.auto_suspend_days = data.auto_suspend_days

    await db.commit()
    await db.refresh(settings)

    return PPPoESettingsResponse(
        require_username_approval=settings.require_username_approval,
        allow_self_registration=settings.allow_self_registration,
        session_timeout_minutes=settings.session_timeout_minutes,
        auto_disconnect_expired=settings.auto_disconnect_expired,
        auto_suspend_days=settings.auto_suspend_days,
    )


# =========================================================================
# Notification Settings
# =========================================================================

class NotificationSettingsResponse(BaseModel):
    """Schema for notification settings response."""

    # MikroTik Status
    enable_mikrotik_status_notifications: bool

    # Payment Confirmation Settings
    send_hotspot_payment_confirmation: bool
    hotspot_payment_confirmation_sms: Optional[str]
    send_pppoe_payment_confirmation: bool
    pppoe_payment_confirmation_sms: Optional[str]

    # Expiry Notification Settings
    send_hotspot_expiry_notification: bool
    hotspot_expiry_notification_sms: Optional[str]
    send_pppoe_expiry_notification: bool
    pppoe_expiry_notification_sms: Optional[str]

    # Expiry Reminder Settings
    send_hotspot_expiry_reminder: bool
    hotspot_expiry_reminder_sms: Optional[str]
    send_pppoe_expiry_reminder: bool
    pppoe_expiry_reminder_sms: Optional[str]

    # Email Reminder Settings
    enable_email_subscription_reminders: bool
    send_pppoe_email_reminders: bool
    pppoe_email_reminder_subject: Optional[str]
    pppoe_email_reminder_message: Optional[str]


class NotificationSettingsUpdate(BaseModel):
    """Schema for updating notification settings."""

    # MikroTik Status
    enable_mikrotik_status_notifications: Optional[bool] = None

    # Payment Confirmation Settings
    send_hotspot_payment_confirmation: Optional[bool] = None
    hotspot_payment_confirmation_sms: Optional[str] = None
    send_pppoe_payment_confirmation: Optional[bool] = None
    pppoe_payment_confirmation_sms: Optional[str] = None

    # Expiry Notification Settings
    send_hotspot_expiry_notification: Optional[bool] = None
    hotspot_expiry_notification_sms: Optional[str] = None
    send_pppoe_expiry_notification: Optional[bool] = None
    pppoe_expiry_notification_sms: Optional[str] = None

    # Expiry Reminder Settings
    send_hotspot_expiry_reminder: Optional[bool] = None
    hotspot_expiry_reminder_sms: Optional[str] = None
    send_pppoe_expiry_reminder: Optional[bool] = None
    pppoe_expiry_reminder_sms: Optional[str] = None

    # Email Reminder Settings
    enable_email_subscription_reminders: Optional[bool] = None
    send_pppoe_email_reminders: Optional[bool] = None
    pppoe_email_reminder_subject: Optional[str] = None
    pppoe_email_reminder_message: Optional[str] = None


@router.get("/notifications", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get notification settings.

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

    return NotificationSettingsResponse(
        enable_mikrotik_status_notifications=settings.enable_mikrotik_status_notifications,
        send_hotspot_payment_confirmation=settings.send_hotspot_payment_confirmation,
        hotspot_payment_confirmation_sms=settings.hotspot_payment_confirmation_sms,
        send_pppoe_payment_confirmation=settings.send_pppoe_payment_confirmation,
        pppoe_payment_confirmation_sms=settings.pppoe_payment_confirmation_sms,
        send_hotspot_expiry_notification=settings.send_hotspot_expiry_notification,
        hotspot_expiry_notification_sms=settings.hotspot_expiry_notification_sms,
        send_pppoe_expiry_notification=settings.send_pppoe_expiry_notification,
        pppoe_expiry_notification_sms=settings.pppoe_expiry_notification_sms,
        send_hotspot_expiry_reminder=settings.send_hotspot_expiry_reminder,
        hotspot_expiry_reminder_sms=settings.hotspot_expiry_reminder_sms,
        send_pppoe_expiry_reminder=settings.send_pppoe_expiry_reminder,
        pppoe_expiry_reminder_sms=settings.pppoe_expiry_reminder_sms,
        enable_email_subscription_reminders=settings.enable_email_subscription_reminders,
        send_pppoe_email_reminders=settings.send_pppoe_email_reminders,
        pppoe_email_reminder_subject=settings.pppoe_email_reminder_subject,
        pppoe_email_reminder_message=settings.pppoe_email_reminder_message,
    )


@router.patch("/notifications", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    data: NotificationSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update notification settings.

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
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(settings, field):
            setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)

    return NotificationSettingsResponse(
        enable_mikrotik_status_notifications=settings.enable_mikrotik_status_notifications,
        send_hotspot_payment_confirmation=settings.send_hotspot_payment_confirmation,
        hotspot_payment_confirmation_sms=settings.hotspot_payment_confirmation_sms,
        send_pppoe_payment_confirmation=settings.send_pppoe_payment_confirmation,
        pppoe_payment_confirmation_sms=settings.pppoe_payment_confirmation_sms,
        send_hotspot_expiry_notification=settings.send_hotspot_expiry_notification,
        hotspot_expiry_notification_sms=settings.hotspot_expiry_notification_sms,
        send_pppoe_expiry_notification=settings.send_pppoe_expiry_notification,
        pppoe_expiry_notification_sms=settings.pppoe_expiry_notification_sms,
        send_hotspot_expiry_reminder=settings.send_hotspot_expiry_reminder,
        hotspot_expiry_reminder_sms=settings.hotspot_expiry_reminder_sms,
        send_pppoe_expiry_reminder=settings.send_pppoe_expiry_reminder,
        pppoe_expiry_reminder_sms=settings.pppoe_expiry_reminder_sms,
        enable_email_subscription_reminders=settings.enable_email_subscription_reminders,
        send_pppoe_email_reminders=settings.send_pppoe_email_reminders,
        pppoe_email_reminder_subject=settings.pppoe_email_reminder_subject,
        pppoe_email_reminder_message=settings.pppoe_email_reminder_message,
    )


# =========================================================================
# WhatsApp Settings
# =========================================================================
# NOTE (Phase C1): all WhatsApp settings + subscription endpoints were removed
# here — WhatsApp messaging, gateways and subscriptions are centralized on
# notifications-api now. ISP admins manage WhatsApp via the notifications-api UI.
