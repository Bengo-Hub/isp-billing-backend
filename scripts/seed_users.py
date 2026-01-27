"""Seed script for users and user-related data."""

import asyncio
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env  # This sets up the environment variables

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.core.logging import get_logger
from app.models.user import User, UserRole, UserStatus, UserSession, UserVerification
from app.models.user_settings import UserSettings, ThemeType, LanguageCode, NotificationPreference
from app.models.organization import Organization
from app.models.rbac import Role

logger = get_logger(__name__)


class UserSeeder:
    """User data seeder with multi-tenancy support."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)
        self.organizations: List[Organization] = []

    async def seed_users(self, count: int = 50, clear_existing: bool = False) -> List[User]:
        """Seed users with realistic data and multi-tenancy support."""
        if clear_existing:
            await self._clear_users()
            if count == 0:
                return []

        # Load organizations for multi-tenancy
        result = await self.db.execute(select(Organization))
        self.organizations = list(result.scalars().all())

        users = []

        # Create platform owner (super admin - no organization)
        platform_owner = await self._create_platform_owner()
        users.append(platform_owner)

        # Create ISP admin and technician users for each organization
        for org in self.organizations:
            isp_admin = await self._create_isp_admin(org)
            users.append(isp_admin)

            technicians = await self._create_isp_technicians(org, count=2)
            users.extend(technicians)

        # Create customer users distributed across organizations
        customers = await self._create_customer_users(count=count - len(users))
        users.extend(customers)

        await self.db.commit()

        self.logger.info(f"Seeded {len(users)} users")
        return users

    async def _create_platform_owner(self) -> User:
        """Create platform owner (super admin) with no organization."""
        admin = User(
            username="platformadmin",
            email="platform@ispbilling.com",
            phone="+254700000001",
            first_name="Platform",
            last_name="Administrator",
            hashed_password=get_password_hash("admin123"),
            role=UserRole.PLATFORM_OWNER,
            organization_id=None,  # Platform owner has no organization
            status=UserStatus.ACTIVE,
            is_verified=True,
            is_active=True,
            email_verified_at=datetime.utcnow(),
            phone_verified_at=datetime.utcnow(),
            bio="Platform administrator with system-wide access",
            last_login=datetime.utcnow()
        )

        self.db.add(admin)
        await self.db.flush()

        # Create admin settings
        admin_settings = UserSettings(
            user_id=admin.id,
            theme=ThemeType.DARK,
            language=LanguageCode.ENGLISH,
            timezone="Africa/Nairobi",
            default_page_size=50,
            email_notifications=NotificationPreference.ALL,
            sms_notifications=NotificationPreference.ALL,
            browser_notifications=NotificationPreference.ALL,
            two_factor_enabled=True,
            developer_mode=True,
            show_debug_info=True
        )

        self.db.add(admin_settings)

        # Set role_id if RBAC role exists
        result = await self.db.execute(select(Role).where(Role.name == "SUPERUSER"))
        role_obj = result.scalar_one_or_none()
        if role_obj:
            admin.role_id = role_obj.id

        self.logger.info("Created platform owner: platformadmin")
        return admin

    async def _create_isp_admin(self, organization: Organization) -> User:
        """Create ISP admin user for an organization."""
        slug = organization.slug.replace("-", "")
        admin = User(
            username=f"{slug}admin",
            email=f"admin@{organization.slug}.co.ke",
            phone=f"+2547{random.randint(10000000, 99999999)}",
            first_name=organization.name.split()[0],
            last_name="Admin",
            hashed_password=get_password_hash("admin123"),
            role=UserRole.ISP_ADMIN,
            organization_id=organization.id,
            status=UserStatus.ACTIVE,
            is_verified=True,
            is_active=True,
            email_verified_at=datetime.utcnow(),
            phone_verified_at=datetime.utcnow(),
            bio=f"Administrator for {organization.name}",
            last_login=datetime.utcnow()
        )

        self.db.add(admin)
        await self.db.flush()

        # Create admin settings
        admin_settings = UserSettings(
            user_id=admin.id,
            theme=ThemeType.DARK,
            language=LanguageCode.ENGLISH,
            timezone="Africa/Nairobi",
            default_page_size=25,
            email_notifications=NotificationPreference.ALL,
            sms_notifications=NotificationPreference.ALL,
            browser_notifications=NotificationPreference.ALL,
        )

        self.db.add(admin_settings)

        # Set role_id if RBAC role exists
        result = await self.db.execute(select(Role).where(Role.name == "ADMIN"))
        role_obj = result.scalar_one_or_none()
        if role_obj:
            admin.role_id = role_obj.id

        self.logger.info(f"Created ISP admin for {organization.name}: {admin.username}")
        return admin

    async def _create_isp_technicians(self, organization: Organization, count: int = 2) -> List[User]:
        """Create ISP technician users for an organization."""
        technicians = []
        slug = organization.slug.replace("-", "")

        technician_data = [
            {
                "first_name": "John",
                "last_name": "Tech",
                "bio": "Senior network technician specializing in MikroTik configuration"
            },
            {
                "first_name": "Jane",
                "last_name": "Engineer",
                "bio": "Network engineer with expertise in PPPoE and Hotspot setup"
            },
            {
                "first_name": "Mike",
                "last_name": "Support",
                "bio": "Customer support specialist and billing expert"
            }
        ]

        for i in range(min(count, len(technician_data))):
            data = technician_data[i]
            username = f"{slug}tech{i+1}"

            technician = User(
                username=username,
                email=f"tech{i+1}@{organization.slug}.co.ke",
                phone=f"+2547{random.randint(10000000, 99999999)}",
                first_name=data["first_name"],
                last_name=data["last_name"],
                hashed_password=get_password_hash("tech123"),
                role=UserRole.ISP_TECHNICIAN,
                organization_id=organization.id,
                status=UserStatus.ACTIVE,
                is_verified=True,
                is_active=True,
                email_verified_at=datetime.utcnow(),
                phone_verified_at=datetime.utcnow(),
                bio=data["bio"],
                last_login=datetime.utcnow() - timedelta(hours=random.randint(1, 24))
            )

            self.db.add(technician)
            await self.db.flush()

            # Create technician settings
            tech_settings = UserSettings(
                user_id=technician.id,
                theme=random.choice([ThemeType.LIGHT, ThemeType.DARK, ThemeType.SYSTEM]),
                language=LanguageCode.ENGLISH,
                timezone="Africa/Nairobi",
                default_page_size=25,
                email_notifications=NotificationPreference.ALL,
                sms_notifications=NotificationPreference.IMPORTANT,
                browser_notifications=NotificationPreference.ALL,
                enable_keyboard_shortcuts=True
            )

            self.db.add(tech_settings)

            # Set role_id if RBAC role exists
            result = await self.db.execute(select(Role).where(Role.name == "TECHNICIAN"))
            role_obj = result.scalar_one_or_none()
            if role_obj:
                technician.role_id = role_obj.id

            technicians.append(technician)

        self.logger.info(f"Created {len(technicians)} technicians for {organization.name}")
        return technicians

    async def _create_customer_users(self, count: int = 47) -> List[User]:
        """Create customer users with realistic data distributed across organizations."""
        customers = []

        # Sample customer data
        first_names = [
            "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
            "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
            "Thomas", "Sarah", "Christopher", "Karen", "Charles", "Nancy", "Daniel", "Lisa",
            "Matthew", "Betty", "Anthony", "Helen", "Mark", "Sandra", "Donald", "Donna",
            "Steven", "Carol", "Paul", "Ruth", "Andrew", "Sharon", "Joshua", "Michelle",
            "Kenneth", "Laura", "Kevin", "Sarah", "Brian", "Kimberly", "George", "Deborah"
        ]

        last_names = [
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
            "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas",
            "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
            "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
            "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
            "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell"
        ]

        domains = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"]
        cities = ["Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret"]

        for i in range(count):
            first_name = random.choice(first_names)
            last_name = random.choice(last_names)
            username = f"{first_name.lower()}{last_name.lower()}{random.randint(1, 999)}"
            email = f"{username}@{random.choice(domains)}"
            phone = f"+25470{random.randint(1000000, 9999999)}"

            # Assign to a random organization (customers belong to an ISP)
            organization = random.choice(self.organizations) if self.organizations else None

            # Create customer
            customer = User(
                username=username,
                email=email,
                phone=phone,
                first_name=first_name,
                last_name=last_name,
                hashed_password=get_password_hash("customer123"),
                role=UserRole.CUSTOMER,
                organization_id=organization.id if organization else None,
                status=random.choice([UserStatus.ACTIVE, UserStatus.PENDING_VERIFICATION]),
                is_verified=random.choice([True, False]),
                is_active=random.choice([True, True, True, False]),  # 75% active
                email_verified_at=datetime.utcnow() - timedelta(days=random.randint(1, 90)) if random.choice([True, False]) else None,
                phone_verified_at=datetime.utcnow() - timedelta(days=random.randint(1, 90)) if random.choice([True, False]) else None,
                bio=f"Customer from {random.choice(cities)}",
                last_login=datetime.utcnow() - timedelta(hours=random.randint(1, 720)) if random.choice([True, False]) else None,
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 365))
            )

            self.db.add(customer)
            await self.db.flush()

            # Create customer settings
            customer_settings = UserSettings(
                user_id=customer.id,
                theme=random.choice(list(ThemeType)),
                language=random.choice([LanguageCode.ENGLISH, LanguageCode.SWAHILI]),
                timezone="Africa/Nairobi",
                default_page_size=random.choice([10, 20, 25, 50]),
                email_notifications=random.choice(list(NotificationPreference)),
                sms_notifications=random.choice(list(NotificationPreference)),
                browser_notifications=random.choice(list(NotificationPreference)),
                notification_sound=random.choice([True, False]),
                enable_keyboard_shortcuts=random.choice([True, False])
            )

            self.db.add(customer_settings)

            # Set role_id if RBAC role exists
            result = await self.db.execute(select(Role).where(Role.name == "CUSTOMER"))
            role_obj = result.scalar_one_or_none()
            if role_obj:
                customer.role_id = role_obj.id

            customers.append(customer)

        self.logger.info(f"Created {len(customers)} customers")
        return customers

    async def _clear_users(self):
        """Clear existing users."""
        from sqlalchemy import delete
        
        # Delete in correct order to respect foreign key constraints
        await self.db.execute(delete(UserSettings))
        await self.db.execute(delete(UserVerification))
        await self.db.execute(delete(UserSession))
        await self.db.execute(delete(User))
        
        await self.db.commit()
        self.logger.info("Cleared existing users")


async def seed_users(count: int = 50, clear_existing: bool = False) -> List[User]:
    """Seed users."""
    async with AsyncSessionLocal() as db:
        seeder = UserSeeder(db)
        return await seeder.seed_users(count, clear_existing)


if __name__ == "__main__":
    asyncio.run(seed_users(count=50, clear_existing=True))
