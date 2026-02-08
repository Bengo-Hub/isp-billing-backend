"""Middleware for auto-seeding demo and superuser accounts."""

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.rbac import Role, SystemLicence, Permission, UserPermission
from app.models.platform_settings import PlatformSettings
from app.models.platform_billing import PlatformSubscriptionTier, TierType
from app.modules.auth import RBACService
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class SeedMiddleware(BaseHTTPMiddleware):
    """Middleware to ensure demo and superuser accounts exist."""

    def __init__(self, app):
        super().__init__(app)
        self._seeded = False

    async def dispatch(self, request: Request, call_next):
        """Ensure seeding is done on first request."""
        # Skip seeding check for CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        if not self._seeded:
            await self._ensure_seeded()
            self._seeded = True

        response = await call_next(request)
        return response

    async def _ensure_seeded(self):
        """Ensure demo and superuser accounts exist."""
        # Create synchronous engine from async database URL
        sync_database_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        sync_engine = create_engine(sync_database_url, pool_pre_ping=True)

        # Create a session factory bound to the synchronous engine to avoid
        # mixing async engine with synchronous sessions (caused AsyncConnection errors)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
        db = SessionLocal()
        try:
            rbac_service = RBACService(db)

            # Initialize system roles and permissions
            logger.info("Initializing RBAC system...")
            roles = rbac_service.initialize_system_roles_and_permissions()
            logger.info(f"Created {len(roles)} system roles")

            # Ensure superuser account exists (always needed)
            superuser = db.query(User).filter(User.username == "superuser").first()
            if not superuser:
                logger.info("Creating superuser account...")
                superuser_role = roles["superuser"]
                superuser = User(
                    username="superuser",
                    email="superuser@codevertexitsolutions.com",
                    first_name="Super",
                    last_name="User",
                    company_name="CodeVertex IT Solutions",
                    hashed_password=get_password_hash(settings.master_password or "superuser123"),
                    role=UserRole.SUPERUSER,
                    status=UserStatus.ACTIVE,
                    is_verified=True,
                    is_active=True
                )
                superuser.role_obj = superuser_role
                db.add(superuser)
                db.flush()
                logger.info("Superuser account created")
            else:
                # Ensure superuser has the correct role
                if not superuser.role_obj or superuser.role_obj.name != "superuser":
                    superuser.role_obj = roles["superuser"]
                    logger.info("Superuser role updated")

            # Seed platform settings (singleton)
            platform_settings = db.query(PlatformSettings).first()
            if not platform_settings:
                logger.info("Seeding platform settings (CodeVertex IT Solutions)...")
                platform_settings = PlatformSettings(
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
                    admin_user_id=superuser.id,
                )
                db.add(platform_settings)
                logger.info("Platform settings seeded")

            # Seed default subscription tiers if none exist
            existing_tiers = db.query(PlatformSubscriptionTier).count()
            if existing_tiers == 0:
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

            # Demo accounts and licence only in non-production environments
            if not settings.is_production:
                # Ensure demo admin account exists
                demo_admin = db.query(User).filter(User.username == "demo").first()
                if not demo_admin:
                    logger.info("Creating demo admin account (dev/staging only)...")
                    admin_role = roles["admin"]
                    demo_admin = User(
                        username="demo",
                        email="demo@codevertexitsolutions.com",
                        first_name="Demo",
                        last_name="Admin",
                        company_name="Demo ISP Company",
                        hashed_password=get_password_hash("demo123"),
                        role=UserRole.ADMIN,
                        status=UserStatus.ACTIVE,
                        is_verified=True,
                        is_active=True
                    )
                    demo_admin.role_obj = admin_role
                    db.add(demo_admin)
                    logger.info("Demo admin account created")
                else:
                    # Ensure demo admin has the correct role
                    if not demo_admin.role_obj or demo_admin.role_obj.name != "admin":
                        demo_admin.role_obj = roles["admin"]
                        logger.info("Demo admin role updated")

                # Ensure demo licence exists
                demo_licence = db.query(SystemLicence).filter(SystemLicence.licence_key == "DEMO-TRIAL-2024").first()
                if not demo_licence:
                    logger.info("Creating demo licence...")
                    demo_licence = rbac_service.create_system_licence(
                        licence_key="DEMO-TRIAL-2024",
                        organization_name="Demo ISP Company",
                        contact_email="demo@codevertexitsolutions.com",
                        contact_phone="+254 700 000 000",
                        licence_type="trial",
                        trial_days=14,
                        max_users=100,
                        max_routers=20
                    )
                    # Activate the trial
                    rbac_service.activate_licence_trial(demo_licence.id)
                    logger.info("Demo licence created and activated")

            db.commit()
            logger.info("RBAC system initialization completed successfully")

        except Exception as e:
            logger.error(f"Error seeding accounts: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
