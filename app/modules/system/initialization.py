"""Auto-initialization service for configurations."""

from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import get_db
from app.core.logging import get_logger
from .configuration import ConfigurationService
from app.core.exceptions import ConfigurationError


class InitializationService:
    """Service for auto-initializing configurations on startup."""

    def __init__(self):
        self.logger = get_logger(__name__)
        self._initialized = False

    async def initialize_all(self, database_url: str, encryption_key: str) -> bool:
        """Initialize configurations."""
        try:
            if self._initialized:
                self.logger.info("System already initialized")
                return True

            self.logger.info("Starting system initialization...")

            # Verify database connection
            await self._verify_database(database_url)

            # Initialize configurations
            await self._initialize_configurations(encryption_key)

            self._initialized = True
            self.logger.info("System initialization completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            return False

    async def _verify_database(self, database_url: str) -> None:
        """Verify database connection. Schema is managed by Alembic."""
        try:
            self.logger.info("Verifying database connection...")
            engine = create_async_engine(database_url)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            self.logger.info("Database connection verified")
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
            raise ConfigurationError(f"Failed to connect to database: {e}")

    async def _initialize_configurations(self, encryption_key: str) -> None:
        """Initialize default configurations."""
        try:
            self.logger.info("Initializing configurations...")

            async for db in get_db():
                config_service = ConfigurationService(db, encryption_key)
                await config_service.initialize_default_configs()
                break

            self.logger.info("Configurations initialized successfully")

        except Exception as e:
            self.logger.error(f"Configuration initialization failed: {e}")
            raise ConfigurationError(f"Failed to initialize configurations: {e}")

    async def is_initialized(self) -> bool:
        """Check if system is already initialized."""
        return self._initialized


# Global initialization service instance
initialization_service = InitializationService()
