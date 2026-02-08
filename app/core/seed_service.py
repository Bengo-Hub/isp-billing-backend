"""Idempotent startup seeding for RBAC, platform settings, and admin user.

Replaces the old SeedMiddleware approach. All seeds run during application
lifespan startup, not on first HTTP request.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.rbac import (
    Role,
    Permission,
    PermissionModule,
    PermissionAction,
    SystemLicence,
)
from app.models.platform_settings import PlatformSettings
from app.models.platform_billing import PlatformSubscriptionTier, TierType
from app.models.organization import Organization, OrganizationType, OrganizationStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-action definitions for all permission combinations
# ---------------------------------------------------------------------------

MODULE_ACTIONS = {
    PermissionModule.DASHBOARD: [PermissionAction.READ],

    PermissionModule.USERS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.CUSTOMERS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.PACKAGES: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.ROUTERS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.PROVISIONING: [PermissionAction.MANAGE],
    PermissionModule.PAYMENTS: [PermissionAction.READ, PermissionAction.MANAGE],
    PermissionModule.PAYMENT_GATEWAYS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.SMS: [PermissionAction.READ, PermissionAction.MANAGE],
    PermissionModule.VOUCHERS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.SETTINGS: [PermissionAction.READ, PermissionAction.UPDATE],
    PermissionModule.REPORTS: [PermissionAction.READ, PermissionAction.MANAGE],
    PermissionModule.NOTIFICATIONS: [PermissionAction.READ, PermissionAction.MANAGE],
    PermissionModule.SUPPORT: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],

    PermissionModule.BILLING: [PermissionAction.READ, PermissionAction.MANAGE],
    PermissionModule.SUBSCRIPTIONS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.ANALYTICS: [PermissionAction.READ],
    PermissionModule.BRANDING: [PermissionAction.READ, PermissionAction.UPDATE],
    PermissionModule.AUDIT_LOGS: [PermissionAction.READ, PermissionAction.MANAGE],
    PermissionModule.BACKUP_RESTORE: [PermissionAction.MANAGE],

    # Platform-level modules (superuser only by default)
    PermissionModule.PLATFORM_ORGANIZATIONS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.PLATFORM_BILLING: [PermissionAction.READ, PermissionAction.MANAGE],
    PermissionModule.PLATFORM_ANALYTICS: [PermissionAction.READ],
    PermissionModule.PLATFORM_CONFIG: [PermissionAction.MANAGE],
    PermissionModule.PLATFORM_TIERS: [PermissionAction.MANAGE],

    PermissionModule.PLATFORM_INTEGRATIONS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.PLATFORM_INTEGRATIONS_SECRETS: [
        PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.MANAGE,
    ],
    PermissionModule.PLATFORM_INTEGRATIONS_URLS: [
        PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.MANAGE,
    ],
    PermissionModule.PLATFORM_PAYMENT_GATEWAYS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.PLATFORM_SMS_GATEWAYS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],
    PermissionModule.PLATFORM_EMAIL_GATEWAYS: [
        PermissionAction.CREATE, PermissionAction.READ,
        PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE,
    ],

    # Tenant-specific configs (ISP Admin)
    PermissionModule.TENANT_PAYMENT_CONFIG: [PermissionAction.READ, PermissionAction.UPDATE],
    PermissionModule.TENANT_SMS_CONFIG: [PermissionAction.READ, PermissionAction.UPDATE],
    PermissionModule.TENANT_PAYOUT_CONFIG: [
        PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE,
    ],

    # Customer portal
    PermissionModule.CUSTOMER_DASHBOARD: [PermissionAction.READ],
    PermissionModule.CUSTOMER_PACKAGES: [PermissionAction.READ],
    PermissionModule.CUSTOMER_PAYMENTS: [PermissionAction.READ],
    PermissionModule.CUSTOMER_USAGE: [PermissionAction.READ],
    PermissionModule.CUSTOMER_PROFILE: [PermissionAction.READ, PermissionAction.UPDATE],
}

# Modules each role can access
ADMIN_MODULES = [
    PermissionModule.DASHBOARD,
    PermissionModule.USERS,
    PermissionModule.CUSTOMERS,
    PermissionModule.PACKAGES,
    PermissionModule.ROUTERS,
    PermissionModule.PROVISIONING,
    PermissionModule.PAYMENTS,
    PermissionModule.PAYMENT_GATEWAYS,
    PermissionModule.SMS,
    PermissionModule.VOUCHERS,
    PermissionModule.SETTINGS,
    PermissionModule.REPORTS,
    PermissionModule.NOTIFICATIONS,
    PermissionModule.SUPPORT,
    PermissionModule.BILLING,
    PermissionModule.SUBSCRIPTIONS,
    PermissionModule.ANALYTICS,
    PermissionModule.BRANDING,
    PermissionModule.AUDIT_LOGS,
    PermissionModule.TENANT_PAYMENT_CONFIG,
    PermissionModule.TENANT_SMS_CONFIG,
    PermissionModule.TENANT_PAYOUT_CONFIG,
]

TECHNICIAN_MODULES = [
    PermissionModule.DASHBOARD,
    PermissionModule.USERS,
    PermissionModule.CUSTOMERS,
    PermissionModule.PACKAGES,
    PermissionModule.ROUTERS,
    PermissionModule.PROVISIONING,
    PermissionModule.PAYMENTS,
    PermissionModule.SMS,
    PermissionModule.VOUCHERS,
    PermissionModule.NOTIFICATIONS,
    PermissionModule.SUPPORT,
    PermissionModule.SUBSCRIPTIONS,
]

CUSTOMER_MODULES = [
    PermissionModule.CUSTOMER_DASHBOARD,
    PermissionModule.CUSTOMER_PACKAGES,
    PermissionModule.CUSTOMER_PAYMENTS,
    PermissionModule.CUSTOMER_USAGE,
    PermissionModule.CUSTOMER_PROFILE,
    PermissionModule.NOTIFICATIONS,
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_startup_seeds() -> None:
    """Run all idempotent seeds during application startup."""
    async with AsyncSessionLocal() as db:
        try:
            # 1. Roles & permissions
            roles = await _seed_rbac(db)

            # 2. Platform admin user
            admin = await _seed_platform_admin(db, roles)

            # 3. Platform settings singleton
            await _seed_platform_settings(db, admin)

            # 4. Default subscription tiers
            await _seed_subscription_tiers(db)

            # 5. Demo data (non-production only)
            if not settings.is_production:
                await _seed_demo_accounts(db, roles)

            await db.commit()
            logger.info("Startup seeding completed successfully")
        except Exception as e:
            await db.rollback()
            logger.error(f"Startup seeding failed: {e}", exc_info=True)
            raise


# ---------------------------------------------------------------------------
# Individual seed helpers (all idempotent)
# ---------------------------------------------------------------------------

async def _get_or_create_role(
    db: AsyncSession, name: str, description: str
) -> Role:
    result = await db.execute(
        select(Role)
        .where(Role.name == name)
        .options(selectinload(Role.permissions))
    )
    role = result.scalar_one_or_none()
    if role:
        return role
    role = Role(name=name, description=description, is_system_role=True)
    db.add(role)
    await db.flush()
    return role


async def _get_or_create_permission(
    db: AsyncSession, module: PermissionModule, action: PermissionAction
) -> Permission:
    result = await db.execute(
        select(Permission).where(
            Permission.module == module,
            Permission.action == action,
            Permission.resource.is_(None),
        )
    )
    perm = result.scalar_one_or_none()
    if perm:
        return perm
    perm = Permission(module=module, action=action)
    db.add(perm)
    await db.flush()
    return perm


async def _seed_rbac(db: AsyncSession) -> dict:
    """Seed system roles and permissions idempotently."""
    logger.info("Initializing RBAC system...")

    # Create system roles
    superuser_role = await _get_or_create_role(db, "superuser", "ISP Software Provider/Developer")
    admin_role = await _get_or_create_role(db, "admin", "ISP Provider Admin")
    technician_role = await _get_or_create_role(db, "technician", "Technical Staff")
    customer_role = await _get_or_create_role(db, "customer", "End Customer")

    # Create all permissions
    all_perms: list[Permission] = []
    for module, actions in MODULE_ACTIONS.items():
        for action in actions:
            perm = await _get_or_create_permission(db, module, action)
            all_perms.append(perm)

    # Superuser gets all permissions
    existing_ids = {p.id for p in superuser_role.permissions}
    for p in all_perms:
        if p.id not in existing_ids:
            superuser_role.permissions.append(p)

    # Admin gets tenant-level permissions
    admin_perms = [p for p in all_perms if p.module in ADMIN_MODULES]
    existing_ids = {p.id for p in admin_role.permissions}
    for p in admin_perms:
        if p.id not in existing_ids:
            admin_role.permissions.append(p)

    # Technician gets operational permissions
    tech_perms = [p for p in all_perms if p.module in TECHNICIAN_MODULES]
    existing_ids = {p.id for p in technician_role.permissions}
    for p in tech_perms:
        if p.id not in existing_ids:
            technician_role.permissions.append(p)

    # Customer gets only customer-portal permissions
    cust_perms = [p for p in all_perms if p.module in CUSTOMER_MODULES]
    existing_ids = {p.id for p in customer_role.permissions}
    for p in cust_perms:
        if p.id not in existing_ids:
            customer_role.permissions.append(p)

    await db.flush()
    logger.info(f"RBAC: {len(all_perms)} permissions across 4 system roles")

    return {
        "superuser": superuser_role,
        "admin": admin_role,
        "technician": technician_role,
        "customer": customer_role,
    }


async def _seed_platform_admin(db: AsyncSession, roles: dict) -> User:
    """Ensure platform admin exists (credentials from env vars)."""
    admin_email = settings.global_admin_email
    admin_password = settings.global_admin_password

    # Check by username first (backward compat), then by email
    result = await db.execute(
        select(User)
        .where(User.username == "superuser")
        .options(selectinload(User.role_obj))
    )
    admin = result.scalar_one_or_none()

    if not admin:
        result = await db.execute(
            select(User)
            .where(User.email == admin_email)
            .options(selectinload(User.role_obj))
        )
        admin = result.scalar_one_or_none()

    if not admin:
        logger.info(f"Creating platform admin: {admin_email}")
        admin = User(
            username="superuser",
            email=admin_email,
            first_name="Platform",
            last_name="Admin",
            company_name="CodeVertex IT Solutions",
            hashed_password=get_password_hash(admin_password),
            role=UserRole.PLATFORM_OWNER,
            status=UserStatus.ACTIVE,
            is_verified=True,
            is_active=True,
        )
        admin.role_obj = roles["superuser"]
        db.add(admin)
        await db.flush()
        logger.info("Platform admin created")
    else:
        # Ensure correct RBAC role is assigned
        if not admin.role_obj or admin.role_obj.name != "superuser":
            admin.role_obj = roles["superuser"]
            logger.info("Platform admin RBAC role updated")

    return admin


async def _seed_platform_settings(db: AsyncSession, admin: User) -> None:
    """Ensure PlatformSettings singleton exists."""
    result = await db.execute(select(PlatformSettings))
    existing = result.scalar_one_or_none()
    if existing:
        return

    logger.info("Seeding platform settings...")
    ps = PlatformSettings(
        company_name="CodeVertex IT Solutions",
        address="OGINGA STREET, BANK ST., PIONEER HSE",
        city="KISUMU",
        country="Kenya",
        phone="254792548766",
        mobile="254742201368",
        email="info@codevertexitsolutions.com",
        logo_url="/images/logo/logo.png",
        primary_color="#ec4899",
        secondary_color="#8b5cf6",
        invoice_prefix="INV",
        currency="KES",
        default_trial_days=14,
        default_grace_period_days=2,
        admin_user_id=admin.id,
    )
    db.add(ps)
    logger.info("Platform settings seeded")


async def _seed_subscription_tiers(db: AsyncSession) -> None:
    """Ensure default subscription tiers exist."""
    result = await db.execute(select(PlatformSubscriptionTier))
    if result.scalars().first() is not None:
        return

    logger.info("Seeding default subscription tiers...")

    hotspot_tier = PlatformSubscriptionTier(
        name="Hotspot Starter",
        description="Starter package for Hotspot ISPs. Base fee + 2% on earnings above KES 10,000.",
        tier_type=TierType.HOTSPOT,
        is_active=True,
        is_default=True,
        base_monthly_fee=500,
        base_quarterly_fee=1350,
        base_yearly_fee=4800,
        currency="KES",
        earnings_threshold=10000,
        earnings_percentage=2.0,
        max_routers=5,
        max_staff_users=3,
        max_sms_per_month=100,
        features={
            "hotspot_portal": True,
            "voucher_system": True,
            "sms_notifications": True,
            "basic_analytics": True,
            "mpesa_integration": True,
        },
        trial_days=14,
        trial_features={
            "hotspot_portal": True,
            "voucher_system": True,
            "sms_notifications": False,
            "basic_analytics": True,
            "mpesa_integration": True,
        },
        display_order=1,
        badge_text="Popular",
        badge_color="#ec4899",
    )
    db.add(hotspot_tier)

    pppoe_tier = PlatformSubscriptionTier(
        name="PPPoE Starter",
        description="Starter package for PPPoE ISPs. KES 25 per customer per month.",
        tier_type=TierType.PPPOE,
        is_active=True,
        is_default=False,
        base_monthly_fee=1000,
        base_quarterly_fee=2700,
        base_yearly_fee=9600,
        currency="KES",
        earnings_threshold=10000,
        earnings_percentage=0,
        min_customers=0,
        max_customers=50,
        per_customer_fee=25,
        max_routers=5,
        max_staff_users=3,
        max_sms_per_month=100,
        features={
            "pppoe_management": True,
            "bandwidth_control": True,
            "sms_notifications": True,
            "basic_analytics": True,
            "mpesa_integration": True,
        },
        trial_days=14,
        trial_features={
            "pppoe_management": True,
            "bandwidth_control": True,
            "sms_notifications": False,
            "basic_analytics": True,
            "mpesa_integration": True,
        },
        display_order=2,
    )
    db.add(pppoe_tier)
    logger.info("Default subscription tiers seeded")


async def _seed_demo_accounts(db: AsyncSession, roles: dict) -> None:
    """Seed demo accounts in non-production environments."""
    # Demo organization
    result = await db.execute(
        select(Organization).where(Organization.slug == "demo-isp")
    )
    demo_org = result.scalar_one_or_none()

    if not demo_org:
        logger.info("Creating demo organization (dev/staging only)...")
        # Get the default hotspot tier for the demo org
        tier_result = await db.execute(
            select(PlatformSubscriptionTier)
            .where(PlatformSubscriptionTier.tier_type == TierType.HOTSPOT)
            .where(PlatformSubscriptionTier.is_default == True)
        )
        default_tier = tier_result.scalar_one_or_none()

        demo_org = Organization(
            name="Demo ISP Company",
            slug="demo-isp",
            organization_type=OrganizationType.HOTSPOT,
            status=OrganizationStatus.TRIAL,
            email="demo@codevertexitsolutions.com",
            phone="+254 700 000 000",
            address="Demo Street, Nairobi",
            city="Nairobi",
            country="Kenya",
            subscription_tier_id=default_tier.id if default_tier else None,
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
            max_routers=5,
            max_customers=100,
            max_users=5,
            features={
                "hotspot_portal": True,
                "voucher_system": True,
                "sms_notifications": True,
                "basic_analytics": True,
                "mpesa_integration": True,
            },
        )
        db.add(demo_org)
        await db.flush()
        logger.info(f"Demo organization created (id={demo_org.id})")

    # Demo admin
    result = await db.execute(
        select(User)
        .where(User.username == "demo")
        .options(selectinload(User.role_obj))
    )
    demo_admin = result.scalar_one_or_none()

    if not demo_admin:
        logger.info("Creating demo admin account (dev/staging only)...")
        demo_admin = User(
            username="demo",
            email="demo@codevertexitsolutions.com",
            first_name="Demo",
            last_name="Admin",
            company_name="Demo ISP Company",
            hashed_password=get_password_hash("demo123"),
            role=UserRole.ISP_ADMIN,
            status=UserStatus.ACTIVE,
            is_verified=True,
            is_active=True,
            organization_id=demo_org.id,
        )
        demo_admin.role_obj = roles["admin"]
        db.add(demo_admin)
        await db.flush()
        logger.info("Demo admin account created")
    else:
        if not demo_admin.role_obj or demo_admin.role_obj.name != "admin":
            demo_admin.role_obj = roles["admin"]
        # Ensure demo admin is linked to the demo org
        if not demo_admin.organization_id:
            demo_admin.organization_id = demo_org.id
            logger.info("Demo admin linked to demo organization")

    # Demo licence
    result = await db.execute(
        select(SystemLicence).where(SystemLicence.licence_key == "DEMO-TRIAL-2024")
    )
    demo_licence = result.scalar_one_or_none()

    if not demo_licence:
        logger.info("Creating demo licence...")
        demo_licence = SystemLicence(
            licence_key="DEMO-TRIAL-2024",
            organization_name="Demo ISP Company",
            contact_email="demo@codevertexitsolutions.com",
            contact_phone="+254 700 000 000",
            licence_type="trial",
            trial_days=14,
            max_users=100,
            max_routers=20,
            trial_started_at=datetime.utcnow(),
            trial_expires_at=datetime.utcnow() + timedelta(days=14),
            is_active=True,
        )
        db.add(demo_licence)
        logger.info("Demo licence created")
