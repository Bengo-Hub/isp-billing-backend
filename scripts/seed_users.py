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

        # Set role_id - REQUIRED for RBAC permissions
        result = await self.db.execute(select(Role).where(Role.name == "SUPERUSER"))
        role_obj = result.scalar_one_or_none()
        if role_obj:
            admin.role_id = role_obj.id
            self.logger.info(f"Assigned RBAC role 'SUPERUSER' (ID: {role_obj.id}) to platformadmin")
        else:
            self.logger.warning("RBAC role 'SUPERUSER' not found! User will have no permissions. Run seed_rbac first.")

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

        # Set role_id - REQUIRED for RBAC permissions
        result = await self.db.execute(select(Role).where(Role.name == "ADMIN"))
        role_obj = result.scalar_one_or_none()
        if role_obj:
            admin.role_id = role_obj.id
            self.logger.info(f"Assigned RBAC role 'ADMIN' (ID: {role_obj.id}) to {admin.username}")
        else:
            self.logger.warning(f"RBAC role 'ADMIN' not found! User {admin.username} will have no permissions. Run seed_rbac first.")

        self.logger.info(f"Created ISP admin for {organization.name}: {admin.username}")
        return admin
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
