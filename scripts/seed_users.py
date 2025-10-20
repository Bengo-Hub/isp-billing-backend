"""Seed script for users and user-related data."""

import asyncio
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env  # This sets up the environment variables

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.core.logging import get_logger
from app.models.user import User, UserRole, UserStatus, UserSession, UserVerification
from app.models.user_settings import UserSettings, ThemeType, LanguageCode, NotificationPreference

logger = get_logger(__name__)


class UserSeeder:
    """User data seeder."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def seed_users(self, count: int = 50, clear_existing: bool = False) -> List[User]:
        """Seed users with realistic data."""
        if clear_existing:
            await self._clear_users()

        users = []
        
        # Create admin user
        admin = await self._create_admin_user()
        users.append(admin)
        
        # Create technician users
        technicians = await self._create_technician_users(count=3)
        users.extend(technicians)
        
        # Create customer users
        customers = await self._create_customer_users(count=count - 4)
        users.extend(customers)
        
        await self.db.commit()
        
        self.logger.info(f"Seeded {len(users)} users")
        return users

    async def _create_admin_user(self) -> User:
        """Create default admin user."""
        admin = User(
            username="admin",
            email="admin@ispbilling.com",
            phone="+254700000001",
            first_name="System",
            last_name="Administrator",
            hashed_password=get_password_hash("admin123"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            is_verified=True,
            is_active=True,
            email_verified_at=datetime.utcnow(),
            phone_verified_at=datetime.utcnow(),
            bio="System administrator with full access to all features",
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
        return admin

    async def _create_technician_users(self, count: int = 3) -> List[User]:
        """Create technician users."""
        technicians = []
        
        technician_data = [
            {
                "username": "tech1",
                "email": "tech1@ispbilling.com",
                "phone": "+254700000002",
                "first_name": "John",
                "last_name": "Technician",
                "bio": "Senior network technician specializing in MikroTik configuration"
            },
            {
                "username": "tech2", 
                "email": "tech2@ispbilling.com",
                "phone": "+254700000003",
                "first_name": "Jane",
                "last_name": "Engineer",
                "bio": "Network engineer with expertise in PPPoE and Hotspot setup"
            },
            {
                "username": "support",
                "email": "support@ispbilling.com", 
                "phone": "+254700000004",
                "first_name": "Mike",
                "last_name": "Support",
                "bio": "Customer support specialist and billing expert"
            }
        ]
        
        for i in range(min(count, len(technician_data))):
            data = technician_data[i]
            
            technician = User(
                username=data["username"],
                email=data["email"],
                phone=data["phone"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                hashed_password=get_password_hash("tech123"),
                role=UserRole.TECHNICIAN,
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
            technicians.append(technician)
        
        return technicians

    async def _create_customer_users(self, count: int = 47) -> List[User]:
        """Create customer users with realistic data."""
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
        
        for i in range(count):
            first_name = random.choice(first_names)
            last_name = random.choice(last_names)
            username = f"{first_name.lower()}{last_name.lower()}{random.randint(1, 999)}"
            email = f"{username}@{random.choice(domains)}"
            phone = f"+25470{random.randint(1000000, 9999999)}"
            
            # Create customer
            customer = User(
                username=username,
                email=email,
                phone=phone,
                first_name=first_name,
                last_name=last_name,
                hashed_password=get_password_hash("customer123"),
                role=UserRole.CUSTOMER,
                status=random.choice([UserStatus.ACTIVE, UserStatus.PENDING_VERIFICATION]),
                is_verified=random.choice([True, False]),
                is_active=random.choice([True, True, True, False]),  # 75% active
                email_verified_at=datetime.utcnow() - timedelta(days=random.randint(1, 90)) if random.choice([True, False]) else None,
                phone_verified_at=datetime.utcnow() - timedelta(days=random.randint(1, 90)) if random.choice([True, False]) else None,
                bio=f"Customer from {random.choice(['Nairobi', 'Mombasa', 'Kisumu', 'Nakuru', 'Eldoret'])}",
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
            customers.append(customer)
        
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
