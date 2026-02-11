"""Seed script for CodeVertex licences and licence-related data."""

import asyncio
import random
import secrets
import string
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.licence import (
    Licence, LicencePayment, LicenceUsageLog, LicenceFeature, LicenceAlert,
    LicenceStatus, LicenceType, LicencePaymentStatus
)
from app.models.user import User, UserRole

logger = get_logger(__name__)


class LicenceSeeder:
    """Licence data seeder."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def seed_licences(self, count: int = 5, clear_existing: bool = False) -> List[Licence]:
        """Seed CodeVertex licences with realistic data."""
        if clear_existing:
            await self._clear_licences()
            if count == 0:
                return []

        licences = []
        
        # Create standard licences
        standard_licences = await self._create_standard_licences()
        licences.extend(standard_licences)
        
        # Create additional licences if needed
        if count > len(standard_licences):
            additional_licences = await self._create_additional_licences(count - len(standard_licences))
            licences.extend(additional_licences)
        
        # Create licence features
        await self._create_licence_features()
        
        # Ensure licences have primary keys assigned before creating dependent records
        await self.db.flush()
        
        # Create licence payments and usage logs
        for licence in licences:
            await self._create_licence_payments(licence)
            await self._create_licence_usage_logs(licence)
        
        await self.db.commit()
        
        self.logger.info(f"Seeded {len(licences)} licences")
        return licences

    async def _create_standard_licences(self) -> List[Licence]:
        """Create standard licence types."""
        licences = []
        
        licence_data = [
            {
                "licence_name": "ISP Billing Pro",
                "licence_type": LicenceType.PROFESSIONAL,
                "organization_name": "TechCorp Solutions Ltd",
                "contact_email": "admin@techcorp.co.ke",
                "contact_phone": "+254700123456",
                "monthly_cost": Decimal("299.00"),
                "max_routers": 10,
                "max_users": 1000,
                "max_concurrent_sessions": 500,
                "status": LicenceStatus.ACTIVE,
                "billing_cycle_months": 1,
                "features": {
                    "router_management": True,
                    "user_management": True,
                    "basic_billing": True,
                    "advanced_billing": True,
                    "basic_reporting": True,
                    "advanced_reporting": True,
                    "email_notifications": True,
                    "sms_notifications": True,
                    "advanced_analytics": True,
                    "api_access": True,
                    "bulk_operations": True
                }
            },
            {
                "licence_name": "ISP Billing Basic",
                "licence_type": LicenceType.BASIC,
                "organization_name": "SmallISP Kenya",
                "contact_email": "admin@smallisp.co.ke",
                "contact_phone": "+254700789012",
                "monthly_cost": Decimal("99.00"),
                "max_routers": 3,
                "max_users": 200,
                "max_concurrent_sessions": 100,
                "status": LicenceStatus.ACTIVE,
                "billing_cycle_months": 1,
                "features": {
                    "router_management": True,
                    "user_management": True,
                    "basic_billing": True,
                    "basic_reporting": True,
                    "email_notifications": True,
                    "sms_notifications": False,
                    "advanced_analytics": False,
                    "api_access": False
                }
            },
            {
                "licence_name": "ISP Billing Enterprise",
                "licence_type": LicenceType.ENTERPRISE,
                "organization_name": "MegaNet Communications",
                "contact_email": "licensing@meganet.co.ke",
                "contact_phone": "+254700345678",
                "monthly_cost": Decimal("999.00"),
                "max_routers": 100,
                "max_users": 10000,
                "max_concurrent_sessions": 5000,
                "status": LicenceStatus.ACTIVE,
                "billing_cycle_months": 12,  # Annual billing
                "features": {
                    "router_management": True,
                    "user_management": True,
                    "basic_billing": True,
                    "advanced_billing": True,
                    "basic_reporting": True,
                    "advanced_reporting": True,
                    "email_notifications": True,
                    "sms_notifications": True,
                    "advanced_analytics": True,
                    "api_access": True,
                    "bulk_operations": True,
                    "white_labeling": True,
                    "priority_support": True,
                    "custom_integrations": True
                }
            },
            {
                "licence_name": "ISP Billing Trial",
                "licence_type": LicenceType.TRIAL,
                "organization_name": "StartupISP",
                "contact_email": "trial@startupisp.co.ke",
                "contact_phone": "+254700901234",
                "monthly_cost": Decimal("0.00"),
                "max_routers": 1,
                "max_users": 50,
                "max_concurrent_sessions": 25,
                "status": LicenceStatus.TRIAL,
                "billing_cycle_months": 1,
                "features": {
                    "router_management": True,
                    "user_management": True,
                    "basic_billing": True,
                    "basic_reporting": True,
                    "email_notifications": False,
                    "sms_notifications": False,
                    "advanced_analytics": False,
                    "api_access": False
                }
            }
        ]
        
        for licence_info in licence_data:
            # Generate licence key
            licence_key = self._generate_licence_key()
            
            # Calculate dates
            issue_date = datetime.utcnow() - timedelta(days=random.randint(1, 90))
            expiry_date = issue_date + timedelta(days=licence_info["billing_cycle_months"] * 30)
            
            licence = Licence(
                licence_key=licence_key,
                licence_name=licence_info["licence_name"],
                licence_type=licence_info["licence_type"],
                status=licence_info["status"],
                issue_date=issue_date,
                expiry_date=expiry_date,
                last_renewal_date=issue_date if licence_info["status"] != LicenceStatus.TRIAL else None,
                max_routers=licence_info["max_routers"],
                max_users=licence_info["max_users"],
                max_concurrent_sessions=licence_info["max_concurrent_sessions"],
                features=licence_info["features"],
                monthly_cost=licence_info["monthly_cost"],
                currency="USD",
                billing_cycle_months=licence_info["billing_cycle_months"],
                current_routers=random.randint(0, licence_info["max_routers"]),
                current_users=random.randint(0, licence_info["max_users"]),
                total_transactions=random.randint(100, 10000),
                auto_renewal_enabled=licence_info["status"] != LicenceStatus.TRIAL,
                renewal_reminder_days=7,
                organization_name=licence_info["organization_name"],
                contact_email=licence_info["contact_email"],
                contact_phone=licence_info["contact_phone"],
                notes=f"Seeded licence for {licence_info['organization_name']}",
                licence_metadata={
                    "seeded": True,
                    "seed_date": datetime.utcnow().isoformat(),
                    "version": "1.0"
                },
                created_at=issue_date
            )
            
            self.db.add(licence)
            licences.append(licence)
        
        return licences

    async def _create_additional_licences(self, count: int) -> List[Licence]:
        """Create additional randomized licences."""
        licences = []
        
        companies = [
            "NetConnect Kenya", "FastLink Communications", "WifiMax Solutions",
            "BroadbandPlus", "ConnectNow ISP", "SpeedNet Kenya", "LinkUp Communications",
            "NetFlow Solutions", "QuickConnect ISP", "TurboNet Kenya"
        ]
        
        for i in range(count):
            company = random.choice(companies)
            licence_type = random.choice(list(LicenceType))
            
            # Configure based on licence type
            if licence_type == LicenceType.TRIAL:
                max_routers = 1
                max_users = 50
                monthly_cost = Decimal("0.00")
                status = LicenceStatus.TRIAL
            elif licence_type == LicenceType.BASIC:
                max_routers = random.randint(1, 5)
                max_users = random.randint(100, 500)
                monthly_cost = Decimal(str(random.randint(50, 150)))
                status = random.choice([LicenceStatus.ACTIVE, LicenceStatus.SUSPENDED])
            elif licence_type == LicenceType.PROFESSIONAL:
                max_routers = random.randint(5, 20)
                max_users = random.randint(500, 2000)
                monthly_cost = Decimal(str(random.randint(200, 500)))
                status = random.choice([LicenceStatus.ACTIVE, LicenceStatus.EXPIRED])
            else:  # ENTERPRISE
                max_routers = random.randint(20, 100)
                max_users = random.randint(2000, 10000)
                monthly_cost = Decimal(str(random.randint(800, 2000)))
                status = LicenceStatus.ACTIVE
            
            licence_key = self._generate_licence_key()
            issue_date = datetime.utcnow() - timedelta(days=random.randint(1, 365))
            
            licence = Licence(
                licence_key=licence_key,
                licence_name=f"{company} - {licence_type.value.title()}",
                licence_type=licence_type,
                status=status,
                issue_date=issue_date,
                expiry_date=issue_date + timedelta(days=30),
                max_routers=max_routers,
                max_users=max_users,
                max_concurrent_sessions=max_users // 2,
                monthly_cost=monthly_cost,
                currency="USD",
                billing_cycle_months=1,
                current_routers=random.randint(0, max_routers),
                current_users=random.randint(0, max_users),
                total_transactions=random.randint(0, 1000),
                auto_renewal_enabled=random.choice([True, False]),
                organization_name=company,
                contact_email=f"admin@{company.lower().replace(' ', '')}.co.ke",
                contact_phone=f"+25470{random.randint(1000000, 9999999)}",
                created_at=issue_date
            )
            
            self.db.add(licence)
            licences.append(licence)
        
        return licences

    async def _create_licence_features(self):
        """Create available licence features."""
        features = [
            {
                "feature_name": "Router Management",
                "feature_code": "router_mgmt",
                "category": "core",
                "display_name": "Router Management",
                "description": "Manage MikroTik routers and devices",
                "is_core_feature": True,
                "minimum_licence_type": LicenceType.TRIAL
            },
            {
                "feature_name": "User Management",
                "feature_code": "user_mgmt", 
                "category": "core",
                "display_name": "User Management",
                "description": "Manage customers and subscriptions",
                "is_core_feature": True,
                "minimum_licence_type": LicenceType.TRIAL
            },
            {
                "feature_name": "Advanced Analytics",
                "feature_code": "advanced_analytics",
                "category": "analytics",
                "display_name": "Advanced Analytics",
                "description": "Revenue forecasting and customer insights",
                "is_core_feature": False,
                "requires_additional_payment": True,
                "additional_cost": Decimal("50.00"),
                "minimum_licence_type": LicenceType.PROFESSIONAL
            },
            {
                "feature_name": "API Access",
                "feature_code": "api_access",
                "category": "integration",
                "display_name": "API Access",
                "description": "Full REST API access for integrations",
                "is_core_feature": False,
                "minimum_licence_type": LicenceType.PROFESSIONAL
            },
            {
                "feature_name": "White Labeling",
                "feature_code": "white_label",
                "category": "branding",
                "display_name": "White Label Branding",
                "description": "Custom branding and white label options",
                "is_core_feature": False,
                "requires_additional_payment": True,
                "additional_cost": Decimal("100.00"),
                "minimum_licence_type": LicenceType.ENTERPRISE
            }
        ]
        
        for feature_data in features:
            feature = LicenceFeature(
                feature_name=feature_data["feature_name"],
                feature_code=feature_data["feature_code"],
                category=feature_data["category"],
                display_name=feature_data["display_name"],
                description=feature_data["description"],
                is_core_feature=feature_data["is_core_feature"],
                requires_additional_payment=feature_data.get("requires_additional_payment", False),
                additional_cost=feature_data.get("additional_cost", Decimal("0.00")),
                usage_limit=-1,  # Unlimited
                available_in_trial=feature_data["is_core_feature"],
                minimum_licence_type=feature_data["minimum_licence_type"]
            )
            
            self.db.add(feature)

    async def _create_licence_payments(self, licence: Licence):
        """Create payment history for a licence."""
        # Create 3-12 months of payment history
        payment_count = random.randint(3, 12)
        
        for i in range(payment_count):
            payment_date = licence.issue_date + timedelta(days=i * 30)
            
            # 90% of payments are successful
            payment_status = random.choices(
                [LicencePaymentStatus.COMPLETED, LicencePaymentStatus.FAILED],
                weights=[90, 10]
            )[0]
            
            # Calculate billing period for this payment
            billing_start = payment_date
            billing_end = payment_date + timedelta(days=30)
            
            payment = LicencePayment(
                licence_id=licence.id,
                amount=licence.monthly_cost,
                currency=licence.currency,
                payment_method="mpesa",
                payment_reference=f"MP{random.randint(100000000, 999999999)}",
                payment_date=payment_date,
                status=payment_status,
                billing_period_start=billing_start,
                billing_period_end=billing_end,
                extends_licence_until=billing_end,
                is_renewal=(i > 0),  # First payment is initial, rest are renewals
                notes=f"Automated payment for {licence.licence_name}"
            )
            
            self.db.add(payment)

    async def _create_licence_usage_logs(self, licence: Licence):
        """Create usage logs for a licence."""
        # Create daily usage logs for the last 30 days
        for i in range(30):
            log_date = datetime.utcnow().date() - timedelta(days=i)
            
            # Simulate realistic usage patterns
            base_routers = licence.current_routers
            base_users = licence.current_users
            
            # Add some variance
            daily_routers = max(0, base_routers + random.randint(-1, 1))
            daily_users = max(0, base_users + random.randint(-50, 100))
            daily_sessions = random.randint(0, min(daily_users, licence.max_concurrent_sessions))
            
            usage_log = LicenceUsageLog(
                licence_id=licence.id,
                log_date=log_date,
                log_type="daily",
                routers_count=daily_routers,
                users_count=daily_users,
                active_sessions=daily_sessions,
                data_transferred_gb=Decimal(str(random.uniform(10.0, 1000.0))),
                total_transactions=random.randint(10, 500),
                api_calls_count=random.randint(0, 10000) if licence.has_feature("api_access") else 0,
                system_uptime_percentage=Decimal(str(random.uniform(95.0, 100.0))),
                average_response_time_ms=random.randint(50, 300),
                error_rate_percentage=Decimal(str(random.uniform(0.0, 5.0))),
                daily_revenue=licence.monthly_cost / 30,
                monthly_revenue=licence.monthly_cost
            )
            
            self.db.add(usage_log)

    def _generate_licence_key(self) -> str:
        """Generate a unique licence key."""
        # Format: XXXX-XXXX-XXXX-XXXX
        segments = []
        for _ in range(4):
            segment = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
            segments.append(segment)
        
        return '-'.join(segments)

    async def _create_additional_licences(self, count: int) -> List[Licence]:
        """Create additional randomized licences."""
        licences = []
        
        for i in range(count):
            licence_type = random.choice(list(LicenceType))
            
            # Configure based on type
            if licence_type == LicenceType.TRIAL:
                monthly_cost = Decimal("0.00")
                max_routers = 1
                max_users = 50
                status = LicenceStatus.TRIAL
            elif licence_type == LicenceType.BASIC:
                monthly_cost = Decimal(str(random.randint(50, 150)))
                max_routers = random.randint(1, 5)
                max_users = random.randint(50, 300)
                status = random.choice(list(LicenceStatus))
            elif licence_type == LicenceType.PROFESSIONAL:
                monthly_cost = Decimal(str(random.randint(200, 600)))
                max_routers = random.randint(5, 25)
                max_users = random.randint(300, 2000)
                status = random.choice(list(LicenceStatus))
            else:  # ENTERPRISE
                monthly_cost = Decimal(str(random.randint(800, 2500)))
                max_routers = random.randint(25, 100)
                max_users = random.randint(2000, 10000)
                status = LicenceStatus.ACTIVE
            
            licence_key = self._generate_licence_key()
            issue_date = datetime.utcnow() - timedelta(days=random.randint(1, 365))
            
            licence = Licence(
                licence_key=licence_key,
                licence_name=f"ISP Licence {licence_type.value.title()} {i+1}",
                licence_type=licence_type,
                status=status,
                issue_date=issue_date,
                expiry_date=issue_date + timedelta(days=30),
                max_routers=max_routers,
                max_users=max_users,
                max_concurrent_sessions=max_users // 2,
                monthly_cost=monthly_cost,
                currency="USD",
                billing_cycle_months=1,
                current_routers=random.randint(0, max_routers),
                current_users=random.randint(0, max_users),
                total_transactions=random.randint(0, 5000),
                auto_renewal_enabled=random.choice([True, False]),
                organization_name=f"ISP Company {i+1}",
                contact_email=f"admin{i+1}@ispcompany.co.ke",
                contact_phone=f"+25470{random.randint(1000000, 9999999)}",
                created_at=issue_date
            )
            
            self.db.add(licence)
            licences.append(licence)
        
        return licences

    async def _clear_licences(self):
        """Clear existing licences."""
        from sqlalchemy import delete
        
        # Delete in correct order
        await self.db.execute(delete(LicenceAlert))
        await self.db.execute(delete(LicenceUsageLog))
        await self.db.execute(delete(LicencePayment))
        await self.db.execute(delete(LicenceFeature))
        await self.db.execute(delete(Licence))
        
        await self.db.commit()
        self.logger.info("Cleared existing licences")


async def seed_licences(count: int = 5, clear_existing: bool = False) -> List[Licence]:
    """Seed licences."""
    async with AsyncSessionLocal() as db:
        seeder = LicenceSeeder(db)
        return await seeder.seed_licences(count, clear_existing)


if __name__ == "__main__":
    asyncio.run(seed_licences(count=5, clear_existing=True))
