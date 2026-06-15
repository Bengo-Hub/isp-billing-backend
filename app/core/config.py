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

    # Platform Admin (picked from env / git secrets)
    global_admin_email: str = "admin@codevertexitsolutions.com"
    global_admin_password: str = "Vertex2020!"  # MUST be changed via env variable in production
    
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

    @model_validator(mode="after")
    def derive_backend_url_from_api_base(self) -> "Settings":
        """Backwards-compatible: if BACKEND_URL is not provided, derive it from
        API_BASE_URL (strip any trailing /api or /api/v1). This prevents a
        Helm/values mismatch where charts set API_BASE_URL but forget BACKEND_URL.
        """
        import os
        if not self.backend_url:
            api_base = os.getenv("API_BASE_URL") or os.getenv("NEXT_PUBLIC_API_URL")
            if api_base:
                # Strip known API path suffixes to get canonical service base
                for suffix in ("/api/v1", "/api"):
                    if api_base.endswith(suffix):
                        api_base = api_base[: -len(suffix)]
                        break
                # Ensure scheme present
                if api_base.startswith("http://") or api_base.startswith("https://"):
                    self.backend_url = api_base
                else:
                    self.backend_url = f"https://{api_base}"
        return self

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

    # Trusted hosts (comma-separated for production)
    allowed_hosts: Optional[str] = None  # e.g., "api.example.com,*.example.com"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        """Parse CORS origins from string or list.

        Previously returned JSON-like strings unchanged which caused the value to
        remain a raw string in some environments. Accept both CSV *and* JSON
        array strings and normalize to a Python list of origins.
        """
        # Accept CSV string (e.g. "https://a.com,https://b.com")
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]

        # If value is a JSON array string (eg. '["https://a.com"]'), parse it
        if isinstance(v, str) and v.startswith("["):
            import json

            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                # Fall through and return the original string so Pydantic can
                # attempt coercion (backwards compatible)
                return v

        # Already a list or other accepted shape — return as-is
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

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
    mikrotik_api_password: str = "Vertex2020!"  # MUST be changed via env variable

    # Router Agent (polling agent installed on MikroTik routers)
    agent_default_poll_interval: int = 10  # seconds between agent polls (low so hotspot create_user lands fast for post-redeem/payment auto-login)
    agent_offline_threshold_multiplier: int = 3  # offline if no poll in interval * multiplier
    agent_command_expiry_hours: int = 1  # default command expiry
    agent_max_commands_per_poll: int = 10  # max commands returned per poll
    agent_script_version: str = "1.0"  # current agent script version

    # VPN overlay (remote Winbox / management). Per-org overrides live in
    # OrganizationSettings.vpn_domain; this is the platform-wide default.
    vpn_domain: str = "vpn.codevertexitsolutions.com"

    # ── WireGuard VPN overlay (router management tunnel) ──
    # The WG server runs in k8s ns `vpn`; routers dial it outbound (NAT-safe).
    # The server keypair lives ONLY in the k8s Secret `wg-server-keys`; the
    # PUBLIC key is injected here so the backend can hand it to routers during
    # bootstrap. The router generates + keeps its OWN private key — it is never
    # transmitted. Empty WG_SERVER_PUBLIC_KEY disables VPN enrollment (the
    # bootstrap script then skips the WireGuard block and routers stay on the
    # polling-agent fallback).
    wg_server_public_key: str = ""  # base64 server pubkey (from wg-server-keys Secret)
    wg_endpoint: str = "vpn.codevertexitsolutions.com:51820"  # host:port routers dial
    wg_subnet: str = "10.8.0.0/16"  # tunnel subnet; server is .1, routers .2+
    # Shared bearer token authenticating the WG server's reconcile loop when it
    # pulls the authoritative peer list (GET /api/v1/vpn/peers). Stored in the
    # backend Secret and the WG server Secret. Empty => peer-list endpoint 503s.
    wg_peer_sync_token: str = ""

    @property
    def wg_enabled(self) -> bool:
        """True when VPN enrollment is configured (server pubkey present)."""
        return bool(self.wg_server_public_key.strip())

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

            # Check admin credentials
            if self.global_admin_password == "superuser123":
                issues.append(
                    "GLOBAL_ADMIN_PASSWORD must be changed from default in production"
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
