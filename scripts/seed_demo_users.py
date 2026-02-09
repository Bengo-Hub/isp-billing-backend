"""Seed demo users for testing MikroTik provisioning (DEV ONLY)."""

import asyncio
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.config import settings
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionType
from app.models.user import User, UserRole
from app.models.plan import ServicePlan
from app.models.router import Router, RouterStatus
from app.models.organization import Organization

logger = get_logger(__name__)


async def create_2min_test_package(db: AsyncSession, organization: Organization) -> ServicePlan:
    """Create a 2-minute test package for demo users."""
    from app.models.plan import ServicePlan, PlanType, PlanStatus, BillingCycle

    # Check if package already exists
    result = await db.execute(
        select(ServicePlan).where(
            ServicePlan.name == "1HR TEST PACKAGE",
            ServicePlan.organization_id == organization.id
        )
    )
    existing_plan = result.scalar_one_or_none()

    if existing_plan:
        logger.info("1-hour test package already exists")
        return existing_plan

    # Create the test package
    test_package = ServicePlan(
        organization_id=organization.id,
        name="1HR TEST PACKAGE",
        description="1-hour test package for MikroTik provisioning testing (DEV ONLY)",
        plan_type=PlanType.BOTH,  # Works for both hotspot and PPPoE
        billing_cycle=BillingCycle.MONTHLY,
        price=Decimal("1.00"),
        currency="KES",
        data_limit=-1,  # Unlimited data
        download_speed=10240,  # 10 Mbps in Kbps
        upload_speed=5120,    # 5 Mbps in Kbps
        time_limit=1,  # 1 hour time limit
        time_limit_type="total",
        validity_days=1,  # Valid for 1 day
        status=PlanStatus.ACTIVE,
        is_popular=False,
        concurrent_sessions=1,
        auto_renewal=False,
        created_at=datetime.utcnow()
    )

    db.add(test_package)
    await db.commit()
    await db.refresh(test_package)

    logger.info(f"Created 2-minute test package: {test_package.name} (ID: {test_package.id})")
    return test_package


async def create_demo_users(db: AsyncSession) -> tuple:
    """Create two demo users (1 hotspot, 1 PPPoE) for testing."""

    # Get the demo ISP organization (not platform org)
    result = await db.execute(
        select(Organization).where(Organization.slug == "demo-isp")
    )
    organization = result.scalar_one_or_none()

    if not organization:
        logger.error("Demo ISP organization not found. Run scripts/add_default_org.py first!")
        return None, None

    # Create the 2-minute test package
    test_package = await create_2min_test_package(db, organization)

    # Get or create a router for this organization
    router_result = await db.execute(
        select(Router).where(
            Router.organization_id == organization.id
        ).limit(1)
    )
    router = router_result.scalar_one_or_none()

    if not router:
        # Create a demo router for testing
        logger.info("Creating demo router for MikroTik testing...")
        router = Router(
            organization_id=organization.id,
            name="MikroTik1",
            description="RB951Ui-2HnD - Demo router for testing provisioning",
            router_type="mikrotik",
            ip_address="192.168.100.7",  # Actual provisioned router IP
            port=8728,
            username="admin",
            password="",  # Empty password for demo
            winbox_port=8291,
            status=RouterStatus.ONLINE,
            is_active=True,
            routeros_version="v7.18.2",
            board_name="RB951Ui-2HnD",
            created_at=datetime.utcnow()
        )
        db.add(router)
        await db.flush()
        logger.info(f"Created demo router: {router.name}")
    else:
        # Update router status to ONLINE for demo purposes
        router.status = RouterStatus.ONLINE
        await db.flush()
        logger.info(f"Using existing router: {router.name}")

    # Check if demo users already exist
    hotspot_user_result = await db.execute(
        select(User).where(User.username == "demo_hotspot")
    )
    hotspot_user = hotspot_user_result.scalar_one_or_none()

    pppoe_user_result = await db.execute(
        select(User).where(User.username == "demo_pppoe")
    )
    pppoe_user = pppoe_user_result.scalar_one_or_none()

    # Create hotspot demo user if doesn't exist
    if not hotspot_user:
        hotspot_user = User(
            username="demo_hotspot",
            email="demo_hotspot@test.local",
            phone="+254799999001",  # Unique demo phone
            first_name="Demo Hotspot",
            last_name="User",
            role=UserRole.CUSTOMER,
            organization_id=organization.id,
            hashed_password="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYVJ8Y9nkZK",  # demo1234
            is_active=True,
            is_verified=True,
            created_at=datetime.utcnow()
        )
        db.add(hotspot_user)
        await db.flush()
        logger.info(f"Created hotspot demo user: {hotspot_user.username}")
    else:
        logger.info(f"Hotspot demo user already exists: {hotspot_user.username}")

    # Create PPPoE demo user if doesn't exist
    if not pppoe_user:
        pppoe_user = User(
            username="demo_pppoe",
            email="demo_pppoe@test.local",
            phone="+254799999002",  # Unique demo phone
            first_name="Demo PPPoE",
            last_name="User",
            role=UserRole.CUSTOMER,
            organization_id=organization.id,
            hashed_password="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYVJ8Y9nkZK",  # demo1234
            is_active=True,
            is_verified=True,
            created_at=datetime.utcnow()
        )
        db.add(pppoe_user)
        await db.flush()
        logger.info(f"Created PPPoE demo user: {pppoe_user.username}")
    else:
        logger.info(f"PPPoE demo user already exists: {pppoe_user.username}")

    # Create subscriptions for demo users
    await create_demo_subscriptions(db, hotspot_user, pppoe_user, test_package, router)

    await db.commit()

    return hotspot_user, pppoe_user


async def create_demo_subscriptions(
    db: AsyncSession,
    hotspot_user: User,
    pppoe_user: User,
    test_package: ServicePlan,
    router: Router
):
    """Create active subscriptions for demo users."""

    start_date = datetime.utcnow()
    end_date = start_date + timedelta(hours=1)

    # Check if subscriptions already exist
    hotspot_sub_result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == hotspot_user.id,
            Subscription.subscription_type == SubscriptionType.HOTSPOT,
            Subscription.status == SubscriptionStatus.ACTIVE
        )
    )
    hotspot_subscription = hotspot_sub_result.scalar_one_or_none()

    if not hotspot_subscription:
        hotspot_subscription = Subscription(
            user_id=hotspot_user.id,
            plan_id=test_package.id,
            router_id=router.id,
            subscription_type=SubscriptionType.HOTSPOT,
            username="demo_hotspot",
            password="demo1234",
            status=SubscriptionStatus.ACTIVE,
            start_date=start_date,
            end_date=end_date,
            is_auto_renewal=False,
            total_bytes_used=Decimal("0"),
            created_at=start_date,
            last_router_sync=start_date
        )
        db.add(hotspot_subscription)
        logger.info(f"Created hotspot subscription for {hotspot_user.username}")
    else:
        logger.info(f"Hotspot subscription already exists for {hotspot_user.username}")

    # PPPoE subscription
    pppoe_sub_result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == pppoe_user.id,
            Subscription.subscription_type == SubscriptionType.PPPOE,
            Subscription.status == SubscriptionStatus.ACTIVE
        )
    )
    pppoe_subscription = pppoe_sub_result.scalar_one_or_none()

    if not pppoe_subscription:
        pppoe_subscription = Subscription(
            user_id=pppoe_user.id,
            plan_id=test_package.id,
            router_id=router.id,
            subscription_type=SubscriptionType.PPPOE,
            username="demo_pppoe",
            password="demo1234",
            status=SubscriptionStatus.ACTIVE,
            start_date=start_date,
            end_date=end_date,
            is_auto_renewal=False,
            total_bytes_used=Decimal("0"),
            created_at=start_date,
            last_router_sync=start_date
        )
        db.add(pppoe_subscription)
        logger.info(f"Created PPPoE subscription for {pppoe_user.username}")
    else:
        logger.info(f"PPPoE subscription already exists for {pppoe_user.username}")

    await db.flush()


async def sync_demo_users_to_mikrotik(db: AsyncSession, hotspot_user: User, pppoe_user: User):
    """Sync demo users to MikroTik (DEV ENVIRONMENT ONLY)."""

    if settings.environment != "development":
        logger.warning("MikroTik sync skipped - not in development environment")
        return

    logger.info("[MIKROTIK SYNC] Syncing demo users to MikroTik...")

    try:
        from app.modules.routers.mikrotik import get_mikrotik_client
        from app.models.router import Router

        # Get hotspot subscription
        hotspot_sub_result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == hotspot_user.id,
                Subscription.subscription_type == SubscriptionType.HOTSPOT,
                Subscription.status == SubscriptionStatus.ACTIVE
            )
        )
        hotspot_subscription = hotspot_sub_result.scalar_one_or_none()

        # Get PPPoE subscription
        pppoe_sub_result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == pppoe_user.id,
                Subscription.subscription_type == SubscriptionType.PPPOE,
                Subscription.status == SubscriptionStatus.ACTIVE
            )
        )
        pppoe_subscription = pppoe_sub_result.scalar_one_or_none()

        if not hotspot_subscription or not pppoe_subscription:
            logger.error("Demo subscriptions not found!")
            return

        # Get router
        router_result = await db.execute(
            select(Router).where(Router.id == hotspot_subscription.router_id)
        )
        router = router_result.scalar_one_or_none()

        if not router:
            logger.error("Router not found!")
            return

        # Initialize MikroTik client
        mikrotik_client = get_mikrotik_client()

        # Connect to router using credentials from DB (same approach as provisioning workflow)
        logger.info(f"[MIKROTIK] Connecting to {router.ip_address} as {router.username}...")
        connection = await mikrotik_client.connect(
            ip_address=router.ip_address,
            username=router.username,
            password=router.password,  # Pull from DB, not hardcoded
            port=router.port or 8728
        )

        # Sync hotspot user
        logger.info(f"[MIKROTIK] Adding hotspot user: {hotspot_subscription.username}")
        await mikrotik_client.create_hotspot_user(
            connection=connection,
            username=hotspot_subscription.username,
            password=hotspot_subscription.password,
            profile="default",
            limit_uptime="1h",  # 1 hour
            comment="Demo hotspot user - DEV ONLY"
        )

        # Sync PPPoE user
        logger.info(f"[MIKROTIK] Adding PPPoE user: {pppoe_subscription.username}")
        await mikrotik_client.create_pppoe_user(
            connection=connection,
            username=pppoe_subscription.username,
            password=pppoe_subscription.password,
            profile="default",
            comment="Demo PPPoE user - DEV ONLY"
        )

        await mikrotik_client.disconnect(router.ip_address, router.port or 8728)

        logger.info("[OK] Demo users synced to MikroTik successfully!")

        # Update last_synced timestamp
        hotspot_subscription.last_synced = datetime.utcnow()
        pppoe_subscription.last_synced = datetime.utcnow()
        await db.commit()

    except Exception as e:
        logger.error(f"[FAIL] Failed to sync demo users to MikroTik: {e}")
        logger.exception(e)


async def seed_demo_users():
    """Main function to seed demo users."""
    logger.info("=" * 60)
    logger.info("[SEED] CREATING DEMO USERS FOR MIKROTIK TESTING")
    logger.info("=" * 60)

    async with AsyncSessionLocal() as db:
        try:
            # Create demo users
            hotspot_user, pppoe_user = await create_demo_users(db)

            if not hotspot_user or not pppoe_user:
                logger.error("[FAIL] Failed to create demo users")
                return

            # Sync to MikroTik (dev only)
            await sync_demo_users_to_mikrotik(db, hotspot_user, pppoe_user)

            logger.info("=" * 60)
            logger.info("[OK] DEMO USERS CREATED SUCCESSFULLY")
            logger.info("=" * 60)
            logger.info("")
            logger.info("[CREDENTIALS] Use these to test MikroTik:")
            logger.info("")
            logger.info("  Hotspot Login:")
            logger.info("    Username: demo_hotspot")
            logger.info("    Password: demo1234")
            logger.info("    Duration: 1 hour")
            logger.info("")
            logger.info("  PPPoE Login:")
            logger.info("    Username: demo_pppoe")
            logger.info("    Password: demo1234")
            logger.info("    Duration: 1 hour")
            logger.info("")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"[ERROR] Failed to seed demo users: {e}")
            logger.exception(e)
            raise


if __name__ == "__main__":
    asyncio.run(seed_demo_users())
