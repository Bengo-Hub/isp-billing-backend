"""Application configuration settings."""

import warnings
from functools import lru_cache
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "ISP Billing System"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    # Database
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # Redis
    redis_url: str
    redis_password: Optional[str] = None

    # Celery
    celery_broker_url: str
    celery_result_backend: str

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Encryption (NEW)
    encryption_key: Optional[str] = None
    master_password: Optional[str] = None
    encryption_salt: Optional[str] = None
    
    @model_validator(mode="after")
    def set_encryption_fallback(self) -> "Settings":
        """Set fallback encryption key for development if not provided."""
        if not self.encryption_key and not self.master_password:
            if self.environment == "development":
                # Use a fallback key derived from secret_key in development only
                import hashlib
                self.encryption_key = hashlib.sha256(self.secret_key.encode()).hexdigest()
                warnings.warn(
                    "No ENCRYPTION_KEY or MASTER_PASSWORD set. Using fallback derived from SECRET_KEY. "
                    "This is only acceptable in development. Set proper encryption keys in production!",
                    UserWarning
                )
        return self

    # URL Configuration
    backend_url: Optional[str] = None  # e.g., https://api.example.com
    frontend_url: Optional[str] = None  # e.g., https://app.example.com
    force_https: bool = False  # Force HTTPS for all integration URLs

    # CORS
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://192.168.100.4:3000",
        "http://192.168.100.4:3001",
        "http://172.31.255.221:3000",
        "http://172.31.255.221:3001",
    ]
    cors_allow_credentials: bool = True

    # MPESA
    mpesa_environment: str = "sandbox"
    mpesa_consumer_key: str
    mpesa_consumer_secret: str
    mpesa_passkey: str
    mpesa_shortcode: str
    mpesa_callback_url: str

    # SMS
    sms_provider: str = "africas_talking"
    africastalking_api_key: Optional[str] = None
    africastalking_username: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None

    # Email
    email_provider: str = "smtp"
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    sendgrid_api_key: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"

    # MikroTik
    mikrotik_default_username: str = "admin"
    mikrotik_default_password: str = "admin"
    mikrotik_default_port: int = 8728
    mikrotik_timeout: int = 10
    mikrotik_default_ip: str = "192.168.88.1"  # Default router IP for provisioning/ping
    mikrotik_default_subnet: str = "192.168.88.0/24"  # Default subnet for provisioning
    # API user credentials (created during bootstrap for secure API access)
    mikrotik_api_username: str = "codevertex_api"
    mikrotik_api_password: str = "changeme_in_production"  # MUST be changed via env variable

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    log_file: Optional[str] = None

    # File Upload
    max_file_size: int = 10485760  # 10MB
    upload_dir: str = "uploads"

    # Security
    bcrypt_rounds: int = 12
    password_min_length: int = 8
    session_timeout: int = 3600

    # Monitoring
    sentry_dsn: Optional[str] = None
    health_check_interval: int = 30

    # Backup
    backup_enabled: bool = True
    backup_schedule: str = "0 2 * * *"  # Daily at 2 AM
    backup_retention_days: int = 30
    backup_s3_bucket: Optional[str] = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment setting."""
        if v not in ["development", "staging", "production"]:
            raise ValueError("Environment must be development, staging, or production")
        return v

    @field_validator("mpesa_environment")
    @classmethod
    def validate_mpesa_environment(cls, v: str) -> str:
        """Validate MPESA environment setting."""
        if v not in ["sandbox", "production"]:
            raise ValueError("MPESA environment must be sandbox or production")
        return v

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Validate that production has proper secrets configured."""
        if self.environment == "production":
            issues = []

            # Check secret_key
            if len(self.secret_key) < 32:
                issues.append("SECRET_KEY must be at least 32 characters in production")
            dangerous_secrets = ["changeme", "secret", "your-secret-key", "changethis"]
            if any(d in self.secret_key.lower() for d in dangerous_secrets):
                issues.append("SECRET_KEY contains default/example values")

            # Check encryption key or master password
            if not self.encryption_key and not self.master_password:
                issues.append(
                    "ENCRYPTION_KEY or MASTER_PASSWORD required in production"
                )

            # Check database URL
            if "localhost" in self.database_url or "127.0.0.1" in self.database_url:
                warnings.warn(
                    "Database URL points to localhost in production environment",
                    UserWarning,
                )

            if issues:
                raise ValueError(
                    f"Production configuration validation failed: {'; '.join(issues)}"
                )

        return self

    @property
    def database_url_sync(self) -> str:
        """Get synchronous database URL for Alembic."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == "development"

    @property
    def is_staging(self) -> bool:
        """Check if running in staging."""
        return self.environment == "staging"

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache. Useful for testing."""
    get_settings.cache_clear()


# Global settings instance
settings = get_settings()
