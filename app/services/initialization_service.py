"""Auto-initialization service for database and admin user."""

import asyncio
from typing import Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import Base, get_db
from app.core.logging import get_logger
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.configuration import Configuration
from app.services.configuration_service import ConfigurationService
from app.core.exceptions import ConfigurationError


class InitializationService:
    """Service for auto-initializing database and admin user."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self._initialized = False
    
    async def initialize_all(self, database_url: str, encryption_key: str) -> bool:
        """Initialize database, configurations, and admin user."""
        try:
            if self._initialized:
                self.logger.info("System already initialized")
                return True
            
            self.logger.info("Starting system initialization...")
            
            # Step 1: Initialize database
            await self._initialize_database(database_url)
            
            # Step 2: Initialize configurations
            await self._initialize_configurations(encryption_key)
            
            # Step 3: Initialize admin user
            await self._initialize_admin_user()
            
            self._initialized = True
            self.logger.info("System initialization completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            return False
    
    async def _initialize_database(self, database_url: str) -> None:
        """Initialize database tables."""
        try:
            self.logger.info("Initializing database...")
            
            # Create async engine
            engine = create_async_engine(database_url)
            
            # Create all tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            # Test connection
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            
            await engine.dispose()
            self.logger.info("Database initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Database initialization failed: {e}")
            raise ConfigurationError(f"Failed to initialize database: {e}")
    
    async def _initialize_configurations(self, encryption_key: str) -> None:
        """Initialize default configurations."""
        try:
            self.logger.info("Initializing configurations...")
            
            # Get database session
            async for db in get_db():
                config_service = ConfigurationService(db, encryption_key)
                await config_service.initialize_default_configs()
                break
            
            self.logger.info("Configurations initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Configuration initialization failed: {e}")
            raise ConfigurationError(f"Failed to initialize configurations: {e}")
    
    async def _initialize_admin_user(self) -> None:
        """Initialize admin user if not exists."""
        try:
            self.logger.info("Checking for admin user...")
            
            # Get database session
            async for db in get_db():
                # Check if admin user exists
                result = await db.execute(
                    select(User).where(User.username == "admin")
                )
                admin_user = result.scalar_one_or_none()
                
                if admin_user:
                    self.logger.info("Admin user already exists")
                    return
                
                # Create admin user
                admin_user = User(
                    username="admin",
                    email="admin@ispbilling.com",
                    full_name="System Administrator",
                    hashed_password=get_password_hash("admin123"),  # Change in production
                    role=UserRole.ADMIN,
                    status=UserStatus.ACTIVE,
                    is_verified=True
                )
                
                db.add(admin_user)
                await db.commit()
                
                self.logger.info("Admin user created successfully")
                self.logger.warning("IMPORTANT: Change admin password in production!")
                break
                
        except Exception as e:
            self.logger.error(f"Admin user initialization failed: {e}")
            raise ConfigurationError(f"Failed to initialize admin user: {e}")
    
    async def is_initialized(self) -> bool:
        """Check if system is already initialized."""
        try:
            # Get database session
            async for db in get_db():
                # Check if admin user exists
                result = await db.execute(
                    select(User).where(User.username == "admin")
                )
                admin_exists = result.scalar_one_or_none() is not None
                
                # Check if configurations exist
                result = await db.execute(
                    select(Configuration).where(Configuration.key == "app_name")
                )
                config_exists = result.scalar_one_or_none() is not None
                
                return admin_exists and config_exists
                
        except Exception as e:
            self.logger.error(f"Failed to check initialization status: {e}")
            return False
    
    async def reset_system(self, database_url: str, encryption_key: str) -> bool:
        """Reset system (drop and recreate all tables)."""
        try:
            self.logger.warning("Resetting system...")
            
            # Create async engine
            engine = create_async_engine(database_url)
            
            # Drop all tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            
            # Recreate all tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            await engine.dispose()
            
            # Reinitialize
            self._initialized = False
            return await self.initialize_all(database_url, encryption_key)
            
        except Exception as e:
            self.logger.error(f"System reset failed: {e}")
            return False


# Global initialization service instance
initialization_service = InitializationService()
