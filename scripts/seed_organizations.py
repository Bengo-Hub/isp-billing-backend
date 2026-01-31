"""Seed script for organizations and platform subscription tiers."""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env  # This sets up the environment variables

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.organization import Organization, OrganizationType, OrganizationStatus, OrganizationSettings
from app.models.platform_billing import PlatformSubscriptionTier, TierType

logger = get_logger(__name__)


class OrganizationSeeder:
    """Organization and platform tier seeder."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def seed_platform_tiers(self, clear_existing: bool = False) -> List[PlatformSubscriptionTier]:
        """Seed platform subscription tiers."""
        if clear_existing:
            await self._clear_tiers()

        tiers = []

        # Hotspot tiers
        hotspot_tiers = [
            {
                "name": "Hotspot Basic",
                "description": "For small hotspot operators getting started",
                "tier_type": TierType.HOTSPOT,
                "base_monthly_fee": 500,
                "base_quarterly_fee": 1350,
                "base_yearly_fee": 5000,
                "earnings_threshold": 10000,
                "earnings_percentage": 2.0,
                "max_routers": 3,
                "max_staff_users": 2,
                "max_sms_per_month": 50,
                "trial_days": 14,
                "is_default": True,
                "display_order": 1,
                "features": {
                    "voucher_system": True,
                    "sms_notifications": True,
                    "basic_analytics": True,
                    "email_support": True,
                }
            },
            {
                "name": "Hotspot Professional",
                "description": "For growing hotspot businesses",
                "tier_type": TierType.HOTSPOT,
                "base_monthly_fee": 1500,
                "base_quarterly_fee": 4050,
                "base_yearly_fee": 15000,
                "earnings_threshold": 25000,
                "earnings_percentage": 1.5,
                "max_routers": 10,
                "max_staff_users": 5,
                "max_sms_per_month": 200,
                "trial_days": 14,
                "display_order": 2,
                "badge_text": "Most Popular",
                "badge_color": "#ec4899",
                "features": {
                    "voucher_system": True,
                    "sms_notifications": True,
                    "advanced_analytics": True,
                    "email_support": True,
                    "priority_support": True,
                    "custom_domain": True,
                    "white_label": True,
                    "api_access": True,
                }
            },
            {
                "name": "Hotspot Enterprise",
                "description": "For large-scale hotspot operations",
                "tier_type": TierType.HOTSPOT,
                "base_monthly_fee": 5000,
                "base_quarterly_fee": 13500,
                "base_yearly_fee": 50000,
                "earnings_threshold": 100000,
                "earnings_percentage": 1.0,
                "max_routers": 50,
                "max_staff_users": 20,
                "max_sms_per_month": 1000,
                "trial_days": 30,
                "display_order": 3,
                "features": {
                    "voucher_system": True,
                    "sms_notifications": True,
                    "advanced_analytics": True,
                    "email_support": True,
                    "priority_support": True,
                    "custom_domain": True,
                    "white_label": True,
                    "api_access": True,
                    "dedicated_support": True,
                    "custom_integrations": True,
                    "sla_guarantee": True,
                }
            },
        ]

        # PPPoE tiers (per-customer pricing model)
        pppoe_tiers = [
            {
                "name": "PPPoE Starter",
                "description": "For small ISPs up to 50 customers",
                "tier_type": TierType.PPPOE,
                "base_monthly_fee": 1000,
                "base_quarterly_fee": 2700,
                "base_yearly_fee": 10000,
                "min_customers": 0,
                "max_customers": 50,
                "per_customer_fee": 25,
                "max_routers": 3,
                "max_staff_users": 3,
                "max_sms_per_month": 100,
                "trial_days": 14,
                "is_default": False,
                "display_order": 4,
                "features": {
                    "pppoe_management": True,
                    "bandwidth_management": True,
                    "sms_notifications": True,
                    "basic_analytics": True,
                    "email_support": True,
                }
            },
            {
                "name": "PPPoE Growth",
                "description": "For growing ISPs up to 200 customers",
                "tier_type": TierType.PPPOE,
                "base_monthly_fee": 3000,
                "base_quarterly_fee": 8100,
                "base_yearly_fee": 30000,
                "min_customers": 51,
                "max_customers": 200,
                "per_customer_fee": 20,
                "max_routers": 10,
                "max_staff_users": 5,
                "max_sms_per_month": 300,
                "trial_days": 14,
                "display_order": 5,
                "badge_text": "Best Value",
                "badge_color": "#8b5cf6",
                "features": {
                    "pppoe_management": True,
                    "bandwidth_management": True,
                    "sms_notifications": True,
                    "advanced_analytics": True,
                    "email_support": True,
                    "priority_support": True,
                    "custom_domain": True,
                    "api_access": True,
                }
            },
            {
                "name": "PPPoE Enterprise",
                "description": "For established ISPs with 200+ customers",
                "tier_type": TierType.PPPOE,
                "base_monthly_fee": 8000,
                "base_quarterly_fee": 21600,
                "base_yearly_fee": 80000,
                "min_customers": 201,
                "max_customers": None,  # Unlimited
                "per_customer_fee": 15,
                "max_routers": 50,
                "max_staff_users": 20,
                "max_sms_per_month": 1000,
                "trial_days": 30,
                "display_order": 6,
                "features": {
                    "pppoe_management": True,
                    "bandwidth_management": True,
                    "sms_notifications": True,
                    "advanced_analytics": True,
                    "email_support": True,
                    "priority_support": True,
                    "custom_domain": True,
                    "white_label": True,
                    "api_access": True,
                    "dedicated_support": True,
                    "custom_integrations": True,
                    "sla_guarantee": True,
                }
            },
        ]

        all_tiers = hotspot_tiers + pppoe_tiers

        for tier_data in all_tiers:
            tier = PlatformSubscriptionTier(
                name=tier_data["name"],
                description=tier_data.get("description"),
                tier_type=tier_data["tier_type"],
                is_active=True,
                is_default=tier_data.get("is_default", False),
                base_monthly_fee=tier_data["base_monthly_fee"],
                base_quarterly_fee=tier_data.get("base_quarterly_fee"),
                base_yearly_fee=tier_data.get("base_yearly_fee"),
                earnings_threshold=tier_data.get("earnings_threshold", 10000),
                earnings_percentage=tier_data.get("earnings_percentage", 2.0),
                min_customers=tier_data.get("min_customers", 0),
                max_customers=tier_data.get("max_customers"),
                per_customer_fee=tier_data.get("per_customer_fee"),
                max_routers=tier_data["max_routers"],
                max_staff_users=tier_data["max_staff_users"],
                max_sms_per_month=tier_data["max_sms_per_month"],
                features=tier_data["features"],
                trial_days=tier_data["trial_days"],
                display_order=tier_data["display_order"],
                badge_text=tier_data.get("badge_text"),
                badge_color=tier_data.get("badge_color"),
            )
            self.db.add(tier)
            tiers.append(tier)

        await self.db.flush()
        self.logger.info(f"Seeded {len(tiers)} platform subscription tiers")
        return tiers

    async def seed_organizations(self, clear_existing: bool = False) -> List[Organization]:
        """Seed demo organizations (ISP providers)."""
        if clear_existing:
            await self._clear_organizations()

        # Get default tiers
        from sqlalchemy import select
        hotspot_tier = await self.db.scalar(
            select(PlatformSubscriptionTier).where(
                PlatformSubscriptionTier.tier_type == TierType.HOTSPOT,
                PlatformSubscriptionTier.is_default == True
            )
        )
        pppoe_tier = await self.db.scalar(
            select(PlatformSubscriptionTier).where(
                PlatformSubscriptionTier.tier_type == TierType.PPPOE,
                PlatformSubscriptionTier.display_order == 4  # Starter tier
            )
        )

        organizations = []

        org_data = [
            {
                "name": "Default Portal",
                "slug": "default",
                "organization_type": OrganizationType.HOTSPOT,
                "status": OrganizationStatus.ACTIVE,
                "email": "portal@default.local",
                "phone": "+254700000001",
                "address": "Default Address",
                "city": "Nairobi",
                "primary_color": "#ec4899",
                "secondary_color": "#8b5cf6",
                "portal_title": "WiFi Portal",
                "portal_description": "Purchase internet packages",
                "subscription_tier_id": hotspot_tier.id if hotspot_tier else None,
                "max_routers": 5,
                "max_customers": 500,
                "max_users": 5,
                "features": {
                    "voucher_system": True,
                    "sms_notifications": True,
                },
            },
            {
                "name": "Demo ISP Kenya",
                "slug": "demo-isp",
                "organization_type": OrganizationType.HYBRID,
                "status": OrganizationStatus.ACTIVE,
                "email": "admin@demoisp.co.ke",
                "phone": "+254700000010",
                "address": "123 Moi Avenue, Nairobi",
                "city": "Nairobi",
                "primary_color": "#ec4899",
                "secondary_color": "#8b5cf6",
                "portal_title": "Demo ISP - Fast Internet",
                "portal_description": "High-speed internet for homes and businesses",
                "subscription_tier_id": hotspot_tier.id if hotspot_tier else None,
                "max_routers": 10,
                "max_customers": 500,
                "max_users": 10,
                "features": {
                    "voucher_system": True,
                    "sms_notifications": True,
                    "advanced_analytics": True,
                },
            },
            {
                "name": "Coastal Net Solutions",
                "slug": "coastal-net",
                "organization_type": OrganizationType.HOTSPOT,
                "status": OrganizationStatus.ACTIVE,
                "email": "info@coastalnet.co.ke",
                "phone": "+254720000020",
                "address": "45 Beach Road, Mombasa",
                "city": "Mombasa",
                "primary_color": "#0ea5e9",
                "secondary_color": "#06b6d4",
                "portal_title": "Coastal Net - Surf the Coast",
                "portal_description": "Premium hotspot services along the coast",
                "subscription_tier_id": hotspot_tier.id if hotspot_tier else None,
                "max_routers": 5,
                "max_customers": 200,
                "max_users": 5,
                "features": {
                    "voucher_system": True,
                    "sms_notifications": True,
                },
            },
            {
                "name": "Highland Connect",
                "slug": "highland-connect",
                "organization_type": OrganizationType.PPPOE,
                "status": OrganizationStatus.TRIAL,
                "email": "support@highlandconnect.co.ke",
                "phone": "+254730000030",
                "address": "78 Main Street, Eldoret",
                "city": "Eldoret",
                "primary_color": "#22c55e",
                "secondary_color": "#10b981",
                "portal_title": "Highland Connect - Reliable Internet",
                "portal_description": "Fiber and wireless internet for the highlands",
                "subscription_tier_id": pppoe_tier.id if pppoe_tier else None,
                "trial_ends_at": datetime.utcnow() + timedelta(days=10),
                "max_routers": 3,
                "max_customers": 100,
                "max_users": 3,
                "features": {
                    "pppoe_management": True,
                    "bandwidth_management": True,
                },
            },
            {
                "name": "Lake Region Broadband",
                "slug": "lake-region",
                "organization_type": OrganizationType.HYBRID,
                "status": OrganizationStatus.ACTIVE,
                "email": "hello@lakeregion.co.ke",
                "phone": "+254740000040",
                "address": "12 Lake Street, Kisumu",
                "city": "Kisumu",
                "primary_color": "#f59e0b",
                "secondary_color": "#eab308",
                "portal_title": "Lake Region Broadband",
                "portal_description": "Connecting the lake region",
                "subscription_tier_id": hotspot_tier.id if hotspot_tier else None,
                "max_routers": 8,
                "max_customers": 300,
                "max_users": 5,
                "features": {
                    "voucher_system": True,
                    "pppoe_management": True,
                    "sms_notifications": True,
                },
            },
        ]

        for data in org_data:
            org = Organization(
                name=data["name"],
                slug=data["slug"],
                organization_type=data["organization_type"],
                status=data["status"],
                email=data["email"],
                phone=data["phone"],
                address=data["address"],
                city=data["city"],
                primary_color=data["primary_color"],
                secondary_color=data.get("secondary_color"),
                portal_title=data.get("portal_title"),
                portal_description=data.get("portal_description"),
                subscription_tier_id=data.get("subscription_tier_id"),
                trial_ends_at=data.get("trial_ends_at"),
                max_routers=data["max_routers"],
                max_customers=data["max_customers"],
                max_users=data["max_users"],
                features=data.get("features", {}),
                activated_at=datetime.utcnow() if data["status"] == OrganizationStatus.ACTIVE else None,
            )
            self.db.add(org)
            await self.db.flush()

            # Create organization settings with hotspot configuration
            # Use different username prefixes for each organization
            username_prefixes = ["C", "H", "P", "L"]
            templates = ["Aurora", "Modern", "Classic", "Minimal"]
            idx = len(organizations)

            settings = OrganizationSettings(
                organization_id=org.id,
                invoice_prefix=data["slug"][:3].upper(),
                voucher_format="XXXX-XXXX" if data["organization_type"] in [OrganizationType.HOTSPOT, OrganizationType.HYBRID] else None,
                # Hotspot user generation settings
                hotspot_username_prefix=username_prefixes[idx % len(username_prefixes)],
                hotspot_username_counter=1,
                hotspot_template=templates[idx % len(templates)],
                prune_inactive_users_days=14,
                hotspot_redirect_url="https://www.google.com",
            )
            self.db.add(settings)

            organizations.append(org)

        await self.db.commit()
        self.logger.info(f"Seeded {len(organizations)} organizations")
        return organizations

    async def _clear_tiers(self):
        """Clear existing platform subscription tiers."""
        await self.db.execute(delete(PlatformSubscriptionTier))
        await self.db.commit()
        self.logger.info("Cleared existing platform subscription tiers")

    async def _clear_organizations(self):
        """Clear existing organizations."""
        await self.db.execute(delete(OrganizationSettings))
        await self.db.execute(delete(Organization))
        await self.db.commit()
        self.logger.info("Cleared existing organizations")


async def seed_platform_tiers(clear_existing: bool = False) -> List[PlatformSubscriptionTier]:
    """Seed platform subscription tiers."""
    async with AsyncSessionLocal() as db:
        seeder = OrganizationSeeder(db)
        return await seeder.seed_platform_tiers(clear_existing)


async def seed_organizations(clear_existing: bool = False) -> List[Organization]:
    """Seed organizations."""
    async with AsyncSessionLocal() as db:
        seeder = OrganizationSeeder(db)
        return await seeder.seed_organizations(clear_existing)


async def seed_all_org_data(clear_existing: bool = False):
    """Seed all organization-related data."""
    async with AsyncSessionLocal() as db:
        seeder = OrganizationSeeder(db)

        # Seed tiers first
        tiers = await seeder.seed_platform_tiers(clear_existing)

        # Then organizations
        orgs = await seeder.seed_organizations(clear_existing=False)

        return {"tiers": tiers, "organizations": orgs}


if __name__ == "__main__":
    asyncio.run(seed_all_org_data(clear_existing=True))
