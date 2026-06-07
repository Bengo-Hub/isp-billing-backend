"""Quick script to add the default organization for portal access."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env  # This sets up the environment variables

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.organization import Organization, OrganizationType, OrganizationStatus, OrganizationSettings
from app.models.platform_billing import PlatformSubscriptionTier, TierType

logger = get_logger(__name__)


async def add_default_organizations():
    """Add the default organizations if they don't exist."""
    async with AsyncSessionLocal() as db:
        created_orgs = []

        # 1. Create Platform Organization (Codevertex)
        # NOTE: This is the PLATFORM ORGANIZATION, not an ISP
        # Platform org should NOT have a subscription_tier_id
        platform_org = await db.scalar(
            select(Organization).where(Organization.slug == "codevertex")
        )

        if not platform_org:
            platform_org = Organization(
                name="Codevertex Africa Limited",  # Fixed typo
                slug="codevertex",
                organization_type=OrganizationType.HOTSPOT,
                status=OrganizationStatus.ACTIVE,
                email="info@codevertexitsolutions.com",
                phone="+254743793901",
                address="Onginga Street, Pioneer, Kisumu",
                city="Kisumu",
                primary_color="#ec4899",
                secondary_color="#8b5cf6",
                portal_title="Platform Admin",
                portal_description="Platform administration",
                subscription_tier_id=None,  # Platform org - no subscription tier
                max_routers=0,  # Platform org doesn't need routers
                max_customers=0,  # Platform org doesn't have customers
                max_users=10,  # Platform admins only
                features={
                    "platform_admin": True,
                },
                activated_at=datetime.utcnow(),
            )
            db.add(platform_org)
            await db.flush()

            # Create organization settings for platform org
            platform_settings = OrganizationSettings(
                organization_id=platform_org.id,
                invoice_prefix="PLT",
                voucher_format="XXXX-XXXX",
                hotspot_username_prefix="P",
                hotspot_username_counter=1,
                hotspot_template="Aurora",
                prune_inactive_users_days=14,
                hotspot_redirect_url="https://www.google.com",
            )
            db.add(platform_settings)

            logger.info(f"Created platform organization (id={platform_org.id})")
            print(f"✓ Created platform organization: Codevertex (id={platform_org.id})")
            created_orgs.append(platform_org)
        else:
            logger.info(f"Platform organization already exists (id={platform_org.id})")
            print(f"✓ Platform organization already exists: Codevertex (id={platform_org.id})")

        # 2. Create Demo ISP Organization
        # This is an actual ISP that will have customers, routers, etc.
        demo_isp = await db.scalar(
            select(Organization).where(Organization.slug == "demo-isp")
        )

        if not demo_isp:
            # Get or create a subscription tier for the demo ISP
            # Use TierType.STANDARD if available; otherwise fall back to TierType.HOTSPOT
            tier_type_value = getattr(TierType, 'STANDARD', None) or TierType.HOTSPOT
            tier = await db.scalar(
                select(PlatformSubscriptionTier).where(
                    PlatformSubscriptionTier.tier_type == tier_type_value
                ).limit(1)
            )

            if not tier:
                # Create a basic subscription tier
                tier = PlatformSubscriptionTier(
                    name="Standard Plan",
                    tier_type=tier_type_value,
                    price_monthly=5000,  # 5000 KES
                    price_annual=50000,  # 50000 KES
                    max_routers=5,
                    max_customers=500,
                    max_users=5,
                    features={
                        "sms_notifications": True,
                        "whatsapp_notifications": True,
                        "email_notifications": True,
                    },
                    is_active=True,
                )
                db.add(tier)
                await db.flush()
                logger.info(f"Created subscription tier (id={tier.id})")

            demo_isp = Organization(
                name="Demo ISP",
                slug="demo-isp",
                organization_type=OrganizationType.HYBRID,  # Supports both hotspot and PPPoE
                status=OrganizationStatus.ACTIVE,
                email="support@demoisp.co.ke",
                phone="+254700000000",
                address="Demo Street, Nairobi",
                city="Nairobi",
                primary_color="#801066",
                secondary_color="#8b5cf6",
                portal_title="Demo ISP Customer Portal",
                portal_description="Manage your internet subscription",
                subscription_tier_id=tier.id,  # ISP org has subscription tier
                max_routers=5,
                max_customers=500,
                max_users=5,
                features={
                    "voucher_system": True,
                    "sms_notifications": True,
                    "whatsapp_notifications": True,
                },
                activated_at=datetime.utcnow(),
            )
            db.add(demo_isp)
            await db.flush()

            # Create organization settings for demo ISP with updated notification templates
            demo_settings = OrganizationSettings(
                organization_id=demo_isp.id,
                invoice_prefix="DEMO",
                voucher_format="XXXX-XXXX",
                hotspot_username_prefix="C",
                hotspot_username_counter=1,
                hotspot_template="Aurora",
                prune_inactive_users_days=14,
                hotspot_redirect_url="https://www.google.com",
                # Updated notification templates with new variables
                hotspot_payment_confirmation_sms="Dear @username, you have successfully subscribed to @package_name. Your subscription will expire on @expiry_date. Your username is @username and password is @password. To login visit @portal_url/buy/@org_slug and click connect.",
                pppoe_payment_confirmation_sms="Hello @first_name, Your PPPoE account has been created. You can use account number: @account_number to pay. Login to your account at @portal_url/portal/pppoe/@org_slug/login using username: @username and password: @password",
                hotspot_expiry_notification_sms="Dear @username, your package has expired. Kindly select another package to continue using the internet.",
                pppoe_expiry_notification_sms="Dear @username, your package has expired. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",
                hotspot_expiry_reminder_sms="Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",
                pppoe_expiry_reminder_sms="Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",
                # WhatsApp templates
                hotspot_payment_confirmation_whatsapp="Hello @username! 👋\n\nYou've successfully subscribed to *@package_name*\n\n✅ Username: @username\n🔑 Password: @password\n📅 Expires: @expiry_date\n\n🌐 Login: @portal_url/buy/@org_slug\n(Click connect and login with your details)\n\nThank you for choosing us!",
                pppoe_payment_confirmation_whatsapp="Hello @first_name! 👋\n\nYour PPPoE account is ready!\n\n*@package_name*\n\n✅ Username: @username\n🔑 Password: @password\n📅 Expires: @expiry_date\n💳 Account Number: @account_number\n\n🌐 Login: @portal_url/portal/pppoe/@org_slug/login\n\nThank you for choosing us!",
                hotspot_expiry_notification_whatsapp="Hello @username! 📢\n\nYour internet package has expired. Please purchase a new package to continue browsing.\n\nThank you!",
                pppoe_expiry_notification_whatsapp="Hello @username! 📢\n\nYour internet subscription has expired.\n\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to continue browsing!",
                hotspot_expiry_reminder_whatsapp="Hello @username! ⏰\n\nYour package expires in *@days_left days*\n\n📅 Expiry Date: @expiry_date\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to avoid interruption!",
                pppoe_expiry_reminder_whatsapp="Hello @username! ⏰\n\nYour subscription expires in *@days_left days*\n\n📅 Expiry Date: @expiry_date\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to stay connected!",
            )
            db.add(demo_settings)

            logger.info(f"Created demo ISP organization (id={demo_isp.id})")
            print(f"✓ Created demo ISP organization: Demo ISP (id={demo_isp.id})")
            created_orgs.append(demo_isp)
        else:
            logger.info(f"Demo ISP organization already exists (id={demo_isp.id})")
            print(f"✓ Demo ISP organization already exists: Demo ISP (id={demo_isp.id})")

        await db.commit()

        print("\n✓ Organization setup complete!")
        print(f"  Platform Org: Codevertex (id={platform_org.id}) - No org_slug in routes")
        print(f"  ISP Org: Demo ISP (id={demo_isp.id}, slug=demo-isp) - Use /demo-isp/... routes")
        print(f"\nPortal URLs:")
        print(f"  Platform Admin: /platform")
        print(f"  Demo ISP Dashboard: /demo-isp/dashboard")
        print(f"  Demo ISP Hotspot Portal: /demo-isp/portal/hotspot")
        print(f"  Demo ISP PPPoE Portal: /demo-isp/portal/pppoe")

        return platform_org, demo_isp


# Backwards compatibility
async def add_default_organization():
    """Backwards compatible wrapper."""
    return await add_default_organizations()


if __name__ == "__main__":
    print("Setting up default organizations...")
    asyncio.run(add_default_organizations())
    print("\n✅ Setup complete!")
