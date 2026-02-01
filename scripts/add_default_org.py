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


async def add_default_organization():
    """Add the default organization if it doesn't exist."""
    async with AsyncSessionLocal() as db:
        # Check if default org already exists
        existing = await db.scalar(
            select(Organization).where(Organization.slug == "default")
        )

        if existing:
            logger.info(f"Default organization already exists (id={existing.id})")
            print(f"✓ Default organization already exists (id={existing.id})")
            return existing

        # Get default hotspot tier
        hotspot_tier = await db.scalar(
            select(PlatformSubscriptionTier).where(
                PlatformSubscriptionTier.tier_type == TierType.HOTSPOT,
                PlatformSubscriptionTier.is_default == True
            )
        )

        # Create default organization
        org = Organization(
            name="Codevertex IT Soltuions",
            slug="codevertex",
            organization_type=OrganizationType.HOTSPOT,
            status=OrganizationStatus.ACTIVE,
            email="info@codevertexitsolutions.com",
            phone="+254743793901",
            address="Onginga Street, Pioneer, Kisumu",
            city="Kisumu",
            primary_color="#ec4899",
            secondary_color="#8b5cf6",
            portal_title="WiFi Portal",
            portal_description="Purchase internet packages",
            subscription_tier_id=hotspot_tier.id if hotspot_tier else None,
            max_routers=5,
            max_customers=500,
            max_users=5,
            features={
                "voucher_system": True,
                "sms_notifications": True,
            },
            activated_at=datetime.utcnow(),
        )
        db.add(org)
        await db.flush()

        # Create organization settings
        settings = OrganizationSettings(
            organization_id=org.id,
            invoice_prefix="DEF",
            voucher_format="XXXX-XXXX",
            hotspot_username_prefix="D",
            hotspot_username_counter=1,
            hotspot_template="Aurora",
            prune_inactive_users_days=14,
            hotspot_redirect_url="https://www.google.com",
        )
        db.add(settings)

        await db.commit()

        logger.info(f"Created default organization (id={org.id})")
        print(f"✓ Created default organization (id={org.id})")
        print(f"  - Name: {org.name}")
        print(f"  - Slug: {org.slug}")
        print(f"  - Portal URL: /portal/buy/{org.slug}")

        return org


if __name__ == "__main__":
    print("Adding default organization...")
    asyncio.run(add_default_organization())
    print("\nDone! You can now access: /portal/buy/{org_slug}")
