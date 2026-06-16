"""Idempotent startup seeding for RBAC, platform settings, and admin user.

Replaces the old SeedMiddleware approach. All seeds run during application
lifespan startup, not on first HTTP request.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, text
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
            # Check if schema tables exist (Alembic migrations may not have run yet)
            result = await db.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables"
                    "  WHERE table_name = 'roles'"
                    ")"
                )
            )
            if not result.scalar():
                logger.warning(
                    "Database tables not found — skipping startup seeds. "
                    "Run 'alembic upgrade head' to create tables."
                )
                return

            # 1. Roles & permissions
            roles = await _seed_rbac(db)

            # 2. Platform admin user
            admin = await _seed_platform_admin(db, roles)

            # 3. Platform settings singleton
            await _seed_platform_settings(db, admin)

            # NOTE: ISP subscription tiers are owned by subscriptions-api (ISP_* plans)
            # with treasury auto-invoicing — no local tier seeding.
            #
            # NOTE: no demo/customer user seeding. Seeding creates ONLY roles +
            # permissions + the platform admin (superuser). The demo ISP tenant
            # (codevertex-demo) and its admin come from the central SSO, not a local
            # seeder, so we never fabricate hotspot/PPPoE customers or demo users.

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
    # Eagerly load permissions to avoid lazy-load MissingGreenlet in async
    await db.refresh(role, ["permissions"])
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

