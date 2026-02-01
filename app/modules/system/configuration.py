"""Configuration management service with encryption support."""

import json
import os
import base64
import secrets
from typing import Any, Dict, List, Optional, Union
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.models.configuration import Configuration, ConfigType
from app.core.logging import get_logger
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ValidationError


# Security constants
PBKDF2_ITERATIONS = 100000
KEY_LENGTH = 32


class ConfigurationService:
    """Configuration management service with encryption.
    
    Uses PBKDF2 key derivation with configurable salt for secure encryption
    of sensitive configuration values.
    
    Security Notes:
        - Salt is loaded from environment variable (ENCRYPTION_SALT)
        - If no salt is configured, generates a random one and logs a warning
        - Never commits salt to source control
        - In production, always set ENCRYPTION_SALT environment variable
    """
    
    def __init__(
        self,
        db: AsyncSession,
        encryption_key: Optional[str] = None,
        encryption_salt: Optional[str] = None,
    ):
        """Initialize configuration service.
        
        Args:
            db: Database session
            encryption_key: Master encryption key (defaults to settings.encryption_key)
            encryption_salt: Salt for key derivation (defaults to settings.encryption_salt)
        """
        self.db = db
        self.logger = get_logger(__name__)
        self._encryption_key = encryption_key or settings.encryption_key
        self._encryption_salt = self._get_salt(encryption_salt)
        self._fernet = None
        self._initialize_encryption()
    
    def _get_salt(self, provided_salt: Optional[str] = None) -> bytes:
        """Get encryption salt securely.
        
        Priority:
        1. Provided salt parameter
        2. ENCRYPTION_SALT from settings/environment
        3. Generate random salt (with warning)
        
        Args:
            provided_salt: Explicitly provided salt
            
        Returns:
            Salt as bytes
        """
        salt_str = provided_salt or settings.encryption_salt
        
        if salt_str:
            return salt_str.encode('utf-8')
        
        # Generate random salt if none provided (for development only)
        self.logger.warning(
            "SECURITY WARNING: No ENCRYPTION_SALT configured. "
            "A random salt will be generated. "
            "Set ENCRYPTION_SALT environment variable in production!"
        )
        return secrets.token_bytes(32)
    
    def _initialize_encryption(self):
        """Initialize encryption with the provided key and salt."""
        if self._encryption_key:
            try:
                # Derive key from password using PBKDF2 with configurable salt
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=KEY_LENGTH,
                    salt=self._encryption_salt,
                    iterations=PBKDF2_ITERATIONS,
                )
                key = base64.urlsafe_b64encode(kdf.derive(self._encryption_key.encode()))
                self._fernet = Fernet(key)
                self.logger.info("Configuration encryption initialized with secure salt")
            except Exception as e:
                self.logger.error(f"Failed to initialize encryption: {e}")
                self._fernet = None
        else:
            self.logger.warning("No encryption key provided, sensitive data will not be encrypted")
    
    def _encrypt_value(self, value: str) -> str:
        """Encrypt a value."""
        if not self._fernet:
            raise ConfigurationError("Encryption not initialized")
        try:
            encrypted_bytes = self._fernet.encrypt(value.encode())
            return base64.urlsafe_b64encode(encrypted_bytes).decode()
        except Exception as e:
            self.logger.error(f"Failed to encrypt value: {e}")
            raise ConfigurationError(f"Encryption failed: {e}")
    
    def _decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a value."""
        if not self._fernet:
            raise ConfigurationError("Encryption not initialized")
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode())
            decrypted_bytes = self._fernet.decrypt(encrypted_bytes)
            return decrypted_bytes.decode()
        except Exception as e:
            self.logger.error(f"Failed to decrypt value: {e}")
            raise ConfigurationError(f"Decryption failed: {e}")
    
    async def get_config(self, key: str, default: Any = None, organization_id: Optional[int] = None) -> Any:
        """Get configuration value by key.

        Args:
            key: Configuration key
            default: Default value if config not found
            organization_id: Organization ID for tenant-scoped configs (None for platform-level)
        """
        try:
            # Build query conditions
            conditions = [
                Configuration.key == key,
                Configuration.is_active == True
            ]

            # Add organization filter
            if organization_id is not None:
                conditions.append(Configuration.organization_id == organization_id)
            else:
                conditions.append(Configuration.organization_id.is_(None))

            result = await self.db.execute(
                select(Configuration).where(and_(*conditions))
            )
            config = result.scalar_one_or_none()

            if not config:
                self.logger.debug(f"Configuration key '{key}' not found, returning default")
                return default

            # Get the appropriate value based on encryption status
            if config.is_encrypted and config.encrypted_value:
                raw_value = self._decrypt_value(config.encrypted_value)
            else:
                raw_value = config.value

            # Convert to appropriate type
            return self._convert_value(raw_value, config.config_type)

        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting config '{key}': {e}")
            raise ConfigurationError(f"Failed to get configuration: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error getting config '{key}': {e}")
            raise ConfigurationError(f"Unexpected error: {e}")
    
    def _convert_value(self, value: str, config_type: ConfigType) -> Any:
        """Convert string value to appropriate type."""
        if value is None:
            return None
        
        try:
            if config_type == ConfigType.STRING:
                return value
            elif config_type == ConfigType.INTEGER:
                return int(value)
            elif config_type == ConfigType.BOOLEAN:
                return value.lower() in ('true', '1', 'yes', 'on')
            elif config_type == ConfigType.JSON:
                return json.loads(value)
            elif config_type == ConfigType.ENCRYPTED:
                return value  # Already decrypted
            else:
                return value
        except (ValueError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to convert value '{value}' to type '{config_type}': {e}")
            raise ConfigurationError(f"Invalid value format: {e}")
    
    async def set_config(
        self,
        key: str,
        value: Any,
        config_type: ConfigType = ConfigType.STRING,
        description: Optional[str] = None,
        is_encrypted: bool = False,
        is_sensitive: bool = False,
        category: Optional[str] = None,
        organization_id: Optional[int] = None
    ) -> Configuration:
        """Set configuration value.

        Args:
            key: Configuration key
            value: Configuration value
            config_type: Type of configuration value
            description: Description of the configuration
            is_encrypted: Whether to encrypt the value
            is_sensitive: Whether the value is sensitive
            category: Configuration category
            organization_id: Organization ID for tenant-scoped configs (None for platform-level)
        """
        try:
            # Validate input
            if not key or not isinstance(key, str):
                raise ValidationError("Configuration key must be a non-empty string")

            # Convert value to string for storage
            if config_type == ConfigType.JSON:
                value_str = json.dumps(value)
            else:
                value_str = str(value)

            # Build query conditions to find existing config
            conditions = [Configuration.key == key]
            if organization_id is not None:
                conditions.append(Configuration.organization_id == organization_id)
            else:
                conditions.append(Configuration.organization_id.is_(None))

            # Check if config already exists
            result = await self.db.execute(
                select(Configuration).where(and_(*conditions))
            )
            config = result.scalar_one_or_none()

            if config:
                # Update existing config
                config.value = value_str if not is_encrypted else None
                config.encrypted_value = self._encrypt_value(value_str) if is_encrypted else None
                config.config_type = config_type
                config.description = description or config.description
                config.is_encrypted = is_encrypted
                config.is_sensitive = is_sensitive
                config.category = category or config.category
                config.is_active = True
            else:
                # Create new config
                config = Configuration(
                    key=key,
                    value=value_str if not is_encrypted else None,
                    encrypted_value=self._encrypt_value(value_str) if is_encrypted else None,
                    config_type=config_type,
                    description=description,
                    is_encrypted=is_encrypted,
                    is_sensitive=is_sensitive,
                    category=category,
                    organization_id=organization_id,
                    is_active=True
                )
                self.db.add(config)

            await self.db.commit()
            await self.db.refresh(config)

            self.logger.info(f"Configuration '{key}' set successfully for org_id={organization_id}")
            return config

        except ValidationError:
            await self.db.rollback()
            raise
        except SQLAlchemyError as e:
            await self.db.rollback()
            self.logger.error(f"Database error setting config '{key}': {e}")
            raise ConfigurationError(f"Failed to set configuration: {e}")
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Unexpected error setting config '{key}': {e}")
            raise ConfigurationError(f"Unexpected error: {e}")
    
    async def get_all_configs(self, category: Optional[str] = None, organization_id: Optional[int] = None) -> List[Configuration]:
        """Get all configurations, optionally filtered by category and organization.

        Args:
            category: Filter by category
            organization_id: Organization ID for tenant-scoped configs (None for platform-level)
        """
        try:
            conditions = [Configuration.is_active == True]

            if category:
                conditions.append(Configuration.category == category)

            # Add organization filter
            if organization_id is not None:
                conditions.append(Configuration.organization_id == organization_id)
            else:
                conditions.append(Configuration.organization_id.is_(None))

            query = select(Configuration).where(and_(*conditions))

            result = await self.db.execute(query)
            configs = result.scalars().all()

            # Decrypt sensitive values for display
            for config in configs:
                if config.is_encrypted and config.encrypted_value:
                    try:
                        config.value = self._decrypt_value(config.encrypted_value)
                    except Exception as e:
                        self.logger.warning(f"Failed to decrypt config '{config.key}': {e}")
                        config.value = "[ENCRYPTED]"

            return configs

        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting all configs: {e}")
            raise ConfigurationError(f"Failed to get configurations: {e}")
    
    async def delete_config(self, key: str, organization_id: Optional[int] = None) -> bool:
        """Delete configuration by key.

        Args:
            key: Configuration key
            organization_id: Organization ID for tenant-scoped configs (None for platform-level)
        """
        try:
            # Build query conditions
            conditions = [Configuration.key == key]
            if organization_id is not None:
                conditions.append(Configuration.organization_id == organization_id)
            else:
                conditions.append(Configuration.organization_id.is_(None))

            result = await self.db.execute(
                select(Configuration).where(and_(*conditions))
            )
            config = result.scalar_one_or_none()

            if not config:
                self.logger.warning(f"Configuration key '{key}' not found for deletion")
                return False

            await self.db.delete(config)
            await self.db.commit()

            self.logger.info(f"Configuration '{key}' deleted successfully for org_id={organization_id}")
            return True

        except SQLAlchemyError as e:
            await self.db.rollback()
            self.logger.error(f"Database error deleting config '{key}': {e}")
            raise ConfigurationError(f"Failed to delete configuration: {e}")
    
    async def initialize_default_configs(self) -> None:
        """Initialize default configuration values."""
        default_configs = [
            # Database settings
            {
                "key": "database_url",
                "value": "postgresql+asyncpg://user:password@localhost/isp_billing",
                "config_type": ConfigType.STRING,
                "description": "Database connection URL",
                "is_sensitive": True,
                "category": "database"
            },
            # Redis settings
            {
                "key": "redis_url",
                "value": "redis://localhost:6379/0",
                "config_type": ConfigType.STRING,
                "description": "Redis connection URL",
                "is_sensitive": True,
                "category": "cache"
            },
            # JWT settings
            {
                "key": "jwt_secret_key",
                "value": "your-secret-key-change-in-production",
                "config_type": ConfigType.ENCRYPTED,
                "description": "JWT secret key for token signing",
                "is_encrypted": True,
                "is_sensitive": True,
                "category": "security"
            },
            {
                "key": "jwt_algorithm",
                "value": "HS256",
                "config_type": ConfigType.STRING,
                "description": "JWT algorithm",
                "category": "security"
            },
            {
                "key": "jwt_access_token_expire_minutes",
                "value": "30",
                "config_type": ConfigType.INTEGER,
                "description": "JWT access token expiration in minutes",
                "category": "security"
            },
            # MPESA settings
            {
                "key": "mpesa_consumer_key",
                "value": "",
                "config_type": ConfigType.ENCRYPTED,
                "description": "MPESA consumer key",
                "is_encrypted": True,
                "is_sensitive": True,
                "category": "payment"
            },
            {
                "key": "mpesa_consumer_secret",
                "value": "",
                "config_type": ConfigType.ENCRYPTED,
                "description": "MPESA consumer secret",
                "is_encrypted": True,
                "is_sensitive": True,
                "category": "payment"
            },
            {
                "key": "mpesa_shortcode",
                "value": "",
                "config_type": ConfigType.STRING,
                "description": "MPESA business shortcode",
                "is_sensitive": True,
                "category": "payment"
            },
            {
                "key": "mpesa_passkey",
                "value": "",
                "config_type": ConfigType.ENCRYPTED,
                "description": "MPESA passkey",
                "is_encrypted": True,
                "is_sensitive": True,
                "category": "payment"
            },
            # Email settings
            {
                "key": "smtp_host",
                "value": "smtp.gmail.com",
                "config_type": ConfigType.STRING,
                "description": "SMTP host for email",
                "category": "email"
            },
            {
                "key": "smtp_port",
                "value": "587",
                "config_type": ConfigType.INTEGER,
                "description": "SMTP port",
                "category": "email"
            },
            {
                "key": "smtp_username",
                "value": "",
                "config_type": ConfigType.ENCRYPTED,
                "description": "SMTP username",
                "is_encrypted": True,
                "is_sensitive": True,
                "category": "email"
            },
            {
                "key": "smtp_password",
                "value": "",
                "config_type": ConfigType.ENCRYPTED,
                "description": "SMTP password",
                "is_encrypted": True,
                "is_sensitive": True,
                "category": "email"
            },
            # Application settings
            {
                "key": "app_name",
                "value": "ISP Billing System",
                "config_type": ConfigType.STRING,
                "description": "Application name",
                "category": "app"
            },
            {
                "key": "app_version",
                "value": "1.0.0",
                "config_type": ConfigType.STRING,
                "description": "Application version",
                "category": "app"
            },
            {
                "key": "debug_mode",
                "value": "false",
                "config_type": ConfigType.BOOLEAN,
                "description": "Debug mode",
                "category": "app"
            },
            # Router settings
            {
                "key": "router_connection_timeout",
                "value": "30",
                "config_type": ConfigType.INTEGER,
                "description": "Router connection timeout in seconds",
                "category": "router"
            },
            {
                "key": "router_sync_interval",
                "value": "300",
                "config_type": ConfigType.INTEGER,
                "description": "Router sync interval in seconds",
                "category": "router"
            },
            # Billing settings
            {
                "key": "billing_cycle_days",
                "value": "30",
                "config_type": ConfigType.INTEGER,
                "description": "Default billing cycle in days",
                "category": "billing"
            },
            {
                "key": "invoice_due_days",
                "value": "7",
                "config_type": ConfigType.INTEGER,
                "description": "Invoice due days",
                "category": "billing"
            },
            {
                "key": "late_fee_percentage",
                "value": "5.0",
                "config_type": ConfigType.STRING,
                "description": "Late fee percentage",
                "category": "billing"
            }
        ]
        
        try:
            for config_data in default_configs:
                # Check if config already exists
                existing = await self.db.execute(
                    select(Configuration).where(Configuration.key == config_data["key"])
                )
                if not existing.scalar_one_or_none():
                    await self.set_config(**config_data)
                    self.logger.info(f"Initialized default config: {config_data['key']}")
            
            self.logger.info("Default configurations initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize default configs: {e}")
            raise ConfigurationError(f"Failed to initialize default configurations: {e}")
