"""Seed script for service plans and package templates."""

import asyncio
import random
import sys
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.plan import ServicePlan, PlanFeature, PlanPricing, PlanType, PlanStatus, BillingCycle
from app.models.package_template import (
    PackageTemplate, PackageCategory, PackageTemplateStatus,
    PackageCategoryConfig, QuickSetup
)

logger = get_logger(__name__)


class PlanSeeder:
    """Service plan and package template seeder."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def seed_plans(self, count: int = 20, clear_existing: bool = False) -> List[ServicePlan]:
        """Seed service plans with realistic ISP packages."""
        if clear_existing:
            await self._clear_plans()
            if count == 0:
                return []

        plans = []
        
        # Create standard ISP packages
        standard_plans = await self._create_standard_plans()
        plans.extend(standard_plans)
        
        # Create additional plans if needed
        if count > len(standard_plans):
            additional_plans = await self._create_additional_plans(count - len(standard_plans))
            plans.extend(additional_plans)
        
        await self.db.commit()
        
        self.logger.info(f"Seeded {len(plans)} service plans")
        return plans

    async def _create_standard_plans(self) -> List[ServicePlan]:
        """Create standard ISP service plans."""
        plans = []
        
        # Hotspot Plans
        hotspot_plans = [
            {
                "name": "Basic Hotspot 1GB",
                "description": "Perfect for light browsing and social media",
                "plan_type": PlanType.HOTSPOT,
                "download_speed": 2,
                "upload_speed": 1,
                "data_limit": 1024,  # 1GB in MB
                "time_limit": -1,
                "validity_days": 1,
                "price": Decimal("50.00"),
                "billing_cycle": BillingCycle.ONE_TIME
            },
            {
                "name": "Standard Hotspot 5GB",
                "description": "Great for regular internet usage",
                "plan_type": PlanType.HOTSPOT,
                "download_speed": 5,
                "upload_speed": 2,
                "data_limit": 5120,  # 5GB in MB
                "time_limit": -1,
                "validity_days": 7,
                "price": Decimal("200.00"),
                "billing_cycle": BillingCycle.WEEKLY
            },
            {
                "name": "Premium Hotspot Unlimited",
                "description": "Unlimited browsing for heavy users",
                "plan_type": PlanType.HOTSPOT,
                "download_speed": 10,
                "upload_speed": 5,
                "data_limit": -1,
                "time_limit": -1,
                "validity_days": 30,
                "price": Decimal("1500.00"),
                "billing_cycle": BillingCycle.MONTHLY
            }
        ]
        
        # PPPoE Plans
        pppoe_plans = [
            {
                "name": "Home Basic 5Mbps",
                "description": "Reliable home internet connection",
                "plan_type": PlanType.PPPOE,
                "download_speed": 5,
                "upload_speed": 2,
                "data_limit": -1,
                "time_limit": -1,
                "validity_days": 30,
                "price": Decimal("2000.00"),
                "billing_cycle": BillingCycle.MONTHLY
            },
            {
                "name": "Home Standard 10Mbps",
                "description": "Fast home internet for families",
                "plan_type": PlanType.PPPOE,
                "download_speed": 10,
                "upload_speed": 5,
                "data_limit": -1,
                "time_limit": -1,
                "validity_days": 30,
                "price": Decimal("3500.00"),
                "billing_cycle": BillingCycle.MONTHLY
            },
            {
                "name": "Business 20Mbps",
                "description": "High-speed internet for small businesses",
                "plan_type": PlanType.PPPOE,
                "download_speed": 20,
                "upload_speed": 10,
                "data_limit": -1,
                "time_limit": -1,
                "validity_days": 30,
                "price": Decimal("6000.00"),
                "billing_cycle": BillingCycle.MONTHLY
            },
            {
                "name": "Enterprise 50Mbps",
                "description": "Enterprise-grade internet with SLA",
                "plan_type": PlanType.PPPOE,
                "download_speed": 50,
                "upload_speed": 25,
                "data_limit": -1,
                "time_limit": -1,
                "validity_days": 30,
                "price": Decimal("15000.00"),
                "billing_cycle": BillingCycle.MONTHLY
            }
        ]
        
        # Create plans
        all_plan_data = hotspot_plans + pppoe_plans
        
        for plan_data in all_plan_data:
            plan = ServicePlan(
                name=plan_data["name"],
                description=plan_data["description"],
                plan_type=plan_data["plan_type"],
                status=PlanStatus.ACTIVE,
                price=plan_data["price"],
                currency="KES",
                billing_cycle=plan_data["billing_cycle"],
                download_speed=plan_data["download_speed"],
                upload_speed=plan_data["upload_speed"],
                data_limit=plan_data["data_limit"],
                time_limit=plan_data["time_limit"],
                validity_days=plan_data["validity_days"],
                sort_order=len(plans) + 1,
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 90))
            )
            
            self.db.add(plan)
            await self.db.flush()
            
            # Create plan features
            features = [
                {
                    "feature_name": "Download Speed",
                    "feature_value": f"{plan_data['download_speed']} Mbps",
                    "feature_type": "speed",
                    "is_core_feature": True
                },
                {
                    "feature_name": "Upload Speed", 
                    "feature_value": f"{plan_data['upload_speed']} Mbps",
                    "feature_type": "speed",
                    "is_core_feature": True
                },
                {
                    "feature_name": "Data Limit",
                    "feature_value": "Unlimited" if plan_data["data_limit"] == -1 else f"{plan_data['data_limit']} MB",
                    "feature_type": "limit",
                    "is_core_feature": True
                },
                {
                    "feature_name": "Validity",
                    "feature_value": f"{plan_data['validity_days']} days",
                    "feature_type": "validity",
                    "is_core_feature": True
                }
            ]
            
            for idx, feature_data in enumerate(features):
                feature = PlanFeature(
                    plan_id=plan.id,
                    feature_name=feature_data["feature_name"],
                    feature_value=feature_data["feature_value"],
                    is_included=feature_data["is_core_feature"],
                    sort_order=idx
                )
                
                self.db.add(feature)
            
            # Create plan pricing tiers (monthly and annual)
            pricing = PlanPricing(
                plan_id=plan.id,
                duration_months=1,  # Monthly
                price=plan_data["price"],
                discount_percentage=Decimal("0"),
                is_active=True
            )
            
            self.db.add(pricing)
            
            # Add annual pricing with discount
            annual_pricing = PlanPricing(
                plan_id=plan.id,
                duration_months=12,  # Annual
                price=plan_data["price"] * 10,  # 2 months free
                discount_percentage=Decimal("16.67"),
                is_active=True
            )
            
            self.db.add(annual_pricing)
            plans.append(plan)
        
        return plans

    async def _create_additional_plans(self, count: int) -> List[ServicePlan]:
        """Create additional randomized plans."""
        plans = []
        
        plan_types = [PlanType.HOTSPOT, PlanType.PPPOE, PlanType.BOTH]
        speeds = [1, 2, 3, 5, 8, 10, 15, 20, 25, 30, 50, 100]
        data_limits = [512, 1024, 2048, 5120, 10240, -1]  # MB or unlimited
        validity_options = [1, 3, 7, 14, 30, 90]
        
        for i in range(count):
            plan_type = random.choice(plan_types)
            download_speed = random.choice(speeds)
            upload_speed = max(1, download_speed // 2)
            data_limit = random.choice(data_limits)
            validity_days = random.choice(validity_options)
            
            # Calculate price based on speed and data
            base_price = download_speed * 100
            if data_limit == -1:  # Unlimited
                base_price *= 1.5
            
            price = Decimal(str(base_price + random.randint(-50, 200)))
            
            plan = ServicePlan(
                name=f"Custom {plan_type.value.title()} {download_speed}Mbps",
                description=f"Custom {plan_type.value} plan with {download_speed}Mbps speed",
                plan_type=plan_type,
                status=random.choice([PlanStatus.ACTIVE, PlanStatus.INACTIVE]),
                price=price,
                currency="KES",
                billing_cycle=BillingCycle.MONTHLY,
                download_speed=download_speed,
                upload_speed=upload_speed,
                data_limit=data_limit,
                time_limit=-1,  # Unlimited
                validity_days=validity_days,
                sort_order=100 + i,
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 180))
            )
            
            self.db.add(plan)
            await self.db.flush()
            
            # Create pricing
            pricing = PlanPricing(
                plan_id=plan.id,
                duration_months=1,
                price=price,
                discount_percentage=Decimal("0"),
                is_active=True
            )
            
            self.db.add(pricing)
            plans.append(plan)
        
        return plans

    async def seed_package_templates(self, count: int = 15, clear_existing: bool = False) -> List[PackageTemplate]:
        """Seed package templates."""
        if clear_existing:
            await self._clear_package_templates()
            if count == 0:
                return []

        templates = []
        
        # Create standard templates
        standard_templates = await self._create_standard_templates()
        templates.extend(standard_templates)
        
        await self.db.commit()
        
        self.logger.info(f"Seeded {len(templates)} package templates")
        return templates

    async def _create_standard_templates(self) -> List[PackageTemplate]:
        """Create standard package templates matching Centipid screenshots."""
        templates = []
        
        template_data = [
            # Popular Packages (Daily)
            {
                "name": "Basic Hotspot",
                "description": "1GB Daily Hotspot - Perfect for light browsing",
                "category": PackageCategory.HOTSPOT,
                "template_code": "HOTSPOT_1GB_DAILY",
                "plan_type": "hotspot",
                "price_template": Decimal("50.00"),
                "download_speed": 2,
                "upload_speed": 1,
                "data_limit": 1024,  # 1GB
                "validity_days": 1,
                "is_default": True,
                "is_featured": True
            },
            {
                "name": "Home Internet Daily",
                "description": "5GB Daily Bundle - Great for home use",
                "category": PackageCategory.DATA_PLANS,
                "template_code": "HOME_5GB_DAILY",
                "plan_type": "hotspot",
                "price_template": Decimal("200.00"),
                "download_speed": 5,
                "upload_speed": 2,
                "data_limit": 5120,  # 5GB
                "validity_days": 1,
                "is_featured": True
            },
            {
                "name": "Data Bundle 10GB",
                "description": "10GB Data Bundle - Weekly package",
                "category": PackageCategory.DATA_PLANS,
                "template_code": "DATA_10GB_WEEKLY",
                "plan_type": "hotspot",
                "price_template": Decimal("500.00"),
                "download_speed": 8,
                "upload_speed": 4,
                "data_limit": 10240,  # 10GB
                "validity_days": 7,
                "is_featured": True
            },
            
            # Business Packages
            {
                "name": "Premium Business",
                "description": "Unlimited 20Mbps - Business Grade",
                "category": PackageCategory.PPPOE,
                "template_code": "BIZ_PREMIUM_20M",
                "plan_type": "pppoe",
                "price_template": Decimal("8000.00"),
                "download_speed": 20,
                "upload_speed": 10,
                "data_limit": -1,  # Unlimited
                "validity_days": 30,
                "is_featured": True
            },
            {
                "name": "Guest WiFi Package",
                "description": "5Mbps Guest Network - Time Limited",
                "category": PackageCategory.HOTSPOT,
                "template_code": "GUEST_WIFI_5M",
                "plan_type": "hotspot",
                "price_template": Decimal("100.00"),
                "download_speed": 5,
                "upload_speed": 2,
                "data_limit": -1,
                "validity_days": 1,
                "is_featured": False
            },
            {
                "name": "Business Starter",
                "description": "10Mbps SME Package - Monthly",
                "category": PackageCategory.PPPOE,
                "template_code": "BIZ_STARTER_10M",
                "plan_type": "pppoe",
                "price_template": Decimal("5000.00"),
                "download_speed": 10,
                "upload_speed": 5,
                "data_limit": -1,
                "validity_days": 30,
                "is_featured": True
            },
            
            # Trial/Promo Packages
            {
                "name": "Free Trial",
                "description": "7-Day Free Trial - 1GB Data",
                "category": PackageCategory.FREE_TRIAL,
                "template_code": "FREE_TRIAL_7D",
                "plan_type": "hotspot",
                "price_template": Decimal("0.00"),
                "download_speed": 2,
                "upload_speed": 1,
                "data_limit": 1024,  # 1GB
                "validity_days": 7,
                "is_default": False,
                "is_featured": False
            },
            {
                "name": "Weekend Special",
                "description": "20GB Weekend Bundle - 3 Days",
                "category": PackageCategory.DATA_PLANS,
                "template_code": "WEEKEND_20GB",
                "plan_type": "hotspot",
                "price_template": Decimal("600.00"),
                "download_speed": 10,
                "upload_speed": 5,
                "data_limit": 20480,  # 20GB
                "validity_days": 3,
                "is_featured": False
            },
            
            # PPPoE Home Packages
            {
                "name": "Home 5Mbps",
                "description": "Unlimited 5Mbps Home Package",
                "category": PackageCategory.PPPOE,
                "template_code": "HOME_PPPOE_5M",
                "plan_type": "pppoe",
                "price_template": Decimal("2000.00"),
                "download_speed": 5,
                "upload_speed": 2,
                "data_limit": -1,
                "validity_days": 30,
                "is_featured": True
            },
            {
                "name": "Family 10Mbps",
                "description": "Unlimited 10Mbps Family Package",
                "category": PackageCategory.PPPOE,
                "template_code": "FAMILY_PPPOE_10M",
                "plan_type": "pppoe",
                "price_template": Decimal("3500.00"),
                "download_speed": 10,
                "upload_speed": 5,
                "data_limit": -1,
                "validity_days": 30,
                "is_featured": True
            },
            {
                "name": "Premium Home 20Mbps",
                "description": "Unlimited 20Mbps Premium Home",
                "category": PackageCategory.PPPOE,
                "template_code": "PREMIUM_HOME_20M",
                "plan_type": "pppoe",
                "price_template": Decimal("6000.00"),
                "download_speed": 20,
                "upload_speed": 10,
                "data_limit": -1,
                "validity_days": 30,
                "is_featured": True
            },
            
            # Student Packages
            {
                "name": "Student Package",
                "description": "Affordable 15GB Student Bundle",
                "category": PackageCategory.DATA_PLANS,
                "template_code": "STUDENT_15GB",
                "plan_type": "hotspot",
                "price_template": Decimal("500.00"),
                "download_speed": 5,
                "upload_speed": 2,
                "data_limit": 15360,  # 15GB
                "validity_days": 30,
                "is_featured": True
            },
            
            # Night Packages
            {
                "name": "Night Owl 50GB",
                "description": "50GB Night Browsing (12AM-6AM)",
                "category": PackageCategory.DATA_PLANS,
                "template_code": "NIGHT_50GB",
                "plan_type": "hotspot",
                "price_template": Decimal("800.00"),
                "download_speed": 15,
                "upload_speed": 7,
                "data_limit": 51200,  # 50GB
                "validity_days": 30,
                "is_featured": False
            },
            
            # Corporate Packages
            {
                "name": "Corporate 50Mbps",
                "description": "Unlimited 50Mbps Corporate Package",
                "category": PackageCategory.PPPOE,
                "template_code": "CORP_PPPOE_50M",
                "plan_type": "pppoe",
                "price_template": Decimal("15000.00"),
                "download_speed": 50,
                "upload_speed": 25,
                "data_limit": -1,
                "validity_days": 30,
                "is_featured": True
            },
            {
                "name": "Enterprise 100Mbps",
                "description": "Unlimited 100Mbps Enterprise Grade",
                "category": PackageCategory.PPPOE,
                "template_code": "ENT_PPPOE_100M",
                "plan_type": "pppoe",
                "price_template": Decimal("30000.00"),
                "download_speed": 100,
                "upload_speed": 50,
                "data_limit": -1,
                "validity_days": 30,
                "is_featured": True
            }
        ]
        
        # Get admin user for created_by (prefer platform owner or ISP admin)
        from app.models.user import User, UserRole
        from sqlalchemy import select, or_
        
        # Prefer platform owner or an ISP admin; fallback to any user if none found
        result = await self.db.execute(
            select(User).where(
                or_(
                    User.role == UserRole.PLATFORM_OWNER,
                    User.role == UserRole.ISP_ADMIN,
                    User.role == UserRole.ADMIN
                )
            ).limit(1)
        )
        admin_user = result.scalar_one_or_none()
        if not admin_user:
            # Pick any existing user as a fallback
            result = await self.db.execute(select(User).limit(1))
            admin_user = result.scalar_one_or_none()
        if not admin_user:
            raise RuntimeError("No users found in database. Seed users before package templates.")
        admin_id = admin_user.id
        
        for template_data in template_data:
            template = PackageTemplate(
                name=template_data["name"],
                description=template_data["description"],
                category=template_data["category"],
                template_code=template_data["template_code"],
                status=PackageTemplateStatus.ACTIVE,
                is_default=template_data.get("is_default", False),
                is_featured=template_data.get("is_featured", False),
                sort_order=len(templates) + 1,
                plan_type=template_data["plan_type"],
                price_template=template_data["price_template"],
                currency="KES",
                billing_cycle="monthly",
                download_speed=template_data["download_speed"],
                upload_speed=template_data["upload_speed"],
                data_limit=template_data["data_limit"],
                time_limit=-1,
                validity_days=template_data["validity_days"],
                configuration_template={
                    "enable_bandwidth_limiting": True,
                    "enable_time_limiting": template_data["data_limit"] != -1,
                    "enable_data_limiting": template_data["data_limit"] != -1,
                    "session_timeout": "1d" if template_data["plan_type"] == "hotspot" else "0",
                    "idle_timeout": "30m" if template_data["plan_type"] == "hotspot" else "0"
                },
                features_template={
                    "captive_portal": template_data["plan_type"] == "hotspot",
                    "bandwidth_limiting": True,
                    "data_limiting": template_data["data_limit"] != -1,
                    "time_limiting": template_data["data_limit"] != -1
                },
                created_by=admin_id,
                tags=f"{template_data['category'].value},{template_data['plan_type']},standard",
                usage_count=random.randint(0, 50),
                success_rate=Decimal(str(random.uniform(85.0, 99.5))),
                average_rating=Decimal(str(random.uniform(4.0, 5.0)))
            )
            
            self.db.add(template)
            templates.append(template)
        
        return templates

    async def seed_package_categories(self, clear_existing: bool = False) -> List[PackageCategoryConfig]:
        """Seed package category configurations."""
        if clear_existing:
            await self._clear_package_categories()
            return []
        categories = []
        
        category_configs = [
            {
                "category": PackageCategory.HOTSPOT,
                "display_name": "Hotspot Packages",
                "description": "WiFi hotspot packages for cafes, hotels, and public spaces",
                "icon": "wifi",
                "color": "#3b82f6",
                "default_billing_cycle": "daily",
                "default_validity_days": 1,
                "supports_hotspot": True,
                "supports_pppoe": False,
                "min_price": Decimal("10.00"),
                "max_price": Decimal("2000.00"),
                "suggested_prices": [50, 100, 200, 500, 1000],
                "default_features": {
                    "captive_portal": True,
                    "bandwidth_limiting": True,
                    "time_limiting": True,
                    "user_isolation": False
                }
            },
            {
                "category": PackageCategory.PPPOE,
                "display_name": "PPPoE Packages",
                "description": "Dedicated internet connections for homes and businesses",
                "icon": "network",
                "color": "#10b981",
                "default_billing_cycle": "monthly",
                "default_validity_days": 30,
                "supports_hotspot": False,
                "supports_pppoe": True,
                "min_price": Decimal("1000.00"),
                "max_price": Decimal("50000.00"),
                "suggested_prices": [2000, 3500, 5000, 8000, 15000],
                "default_features": {
                    "bandwidth_limiting": True,
                    "static_ip": False,
                    "radius_auth": True
                }
            },
            {
                "category": PackageCategory.DATA_PLANS,
                "display_name": "Data Plans",
                "description": "Data-only packages for mobile and tablet users",
                "icon": "smartphone",
                "color": "#f59e0b",
                "default_billing_cycle": "monthly",
                "default_validity_days": 30,
                "supports_hotspot": True,
                "supports_pppoe": False,
                "min_price": Decimal("100.00"),
                "max_price": Decimal("5000.00"),
                "suggested_prices": [300, 500, 1000, 2000, 3000],
                "default_features": {
                    "data_tracking": True,
                    "fup_support": True,
                    "speed_boost": False
                }
            },
            {
                "category": PackageCategory.FREE_TRIAL,
                "display_name": "Free Trial",
                "description": "Free trial packages for new customers",
                "icon": "gift",
                "color": "#8b5cf6",
                "default_billing_cycle": "one_time",
                "default_validity_days": 7,
                "supports_hotspot": True,
                "supports_pppoe": True,
                "min_price": Decimal("0.00"),
                "max_price": Decimal("0.00"),
                "suggested_prices": [0],
                "default_features": {
                    "limited_access": True,
                    "upgrade_prompts": True,
                    "usage_notifications": True
                }
            }
        ]
        
        for config_data in category_configs:
            config = PackageCategoryConfig(
                category=config_data["category"],
                display_name=config_data["display_name"],
                description=config_data["description"],
                icon=config_data["icon"],
                color=config_data["color"],
                default_billing_cycle=config_data["default_billing_cycle"],
                default_validity_days=config_data["default_validity_days"],
                supports_hotspot=config_data["supports_hotspot"],
                supports_pppoe=config_data["supports_pppoe"],
                min_price=config_data["min_price"],
                max_price=config_data["max_price"],
                suggested_prices=config_data["suggested_prices"],
                default_features=config_data["default_features"],
                is_visible=True,
                sort_order=len(categories) + 1,
                show_in_public=True
            )
            
            self.db.add(config)
            categories.append(config)
        
        await self.db.commit()
        
        self.logger.info(f"Seeded {len(categories)} package categories")
        return categories

    async def _clear_plans(self):
        """Clear existing plans."""
        from sqlalchemy import delete
        
        # Delete in correct order
        await self.db.execute(delete(PlanPricing))
        await self.db.execute(delete(PlanFeature))
        await self.db.execute(delete(ServicePlan))
        
        await self.db.commit()
        self.logger.info("Cleared existing plans")

    async def _clear_package_templates(self):
        """Clear existing package templates."""
        from sqlalchemy import delete
        
        await self.db.execute(delete(PackageCategoryConfig))
        await self.db.execute(delete(PackageTemplate))
        
        await self.db.commit()
        self.logger.info("Cleared existing package templates")

    async def _clear_package_categories(self):
        """Clear existing package category configurations."""
        from sqlalchemy import delete
        
        await self.db.execute(delete(PackageCategoryConfig))
        
        await self.db.commit()
        self.logger.info("Cleared existing package category configs")


async def seed_plans(count: int = 20, clear_existing: bool = False) -> List[ServicePlan]:
    """Seed service plans."""
    async with AsyncSessionLocal() as db:
        seeder = PlanSeeder(db)
        return await seeder.seed_plans(count, clear_existing)


async def seed_package_templates(count: int = 15, clear_existing: bool = False) -> List[PackageTemplate]:
    """Seed package templates."""
    async with AsyncSessionLocal() as db:
        seeder = PlanSeeder(db)
        return await seeder.seed_package_templates(count, clear_existing)


async def seed_package_categories(clear_existing: bool = False) -> List[PackageCategoryConfig]:
    """Seed package categories."""
    async with AsyncSessionLocal() as db:
        seeder = PlanSeeder(db)
        return await seeder.seed_package_categories(clear_existing)


if __name__ == "__main__":
    asyncio.run(seed_plans(count=20, clear_existing=True))
