"""Email Gateway Configuration model for platform-level SMTP settings."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    JSON,
)

from app.core.database import Base


class EmailProvider(str, PyEnum):
    """Email service provider types."""

    SMTP = "smtp"
    SENDGRID = "sendgrid"
    MAILGUN = "mailgun"
    SES = "ses"  # Amazon SES
    CUSTOM = "custom"


class EmailGatewayStatus(str, PyEnum):
    """Email gateway status."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    TESTING = "testing"
    ERROR = "error"


class EmailGatewayConfig(Base):
    """
    Email Gateway Configuration for platform-level email settings.

    Stores SMTP and email service provider credentials for sending platform emails.
    Platform owner only.
    """

    __tablename__ = "email_gateway_configs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Gateway info
    provider_type = Column(Enum(EmailProvider), default=EmailProvider.SMTP, nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "Primary SMTP", "SendGrid"
    description = Column(Text, nullable=True)

    # Status
    status = Column(Enum(EmailGatewayStatus), default=EmailGatewayStatus.INACTIVE, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)  # Only one can be primary

    # SMTP Configuration
    smtp_host = Column(String(255), nullable=True)
    smtp_port = Column(Integer, default=587, nullable=True)
    smtp_username = Column(String(255), nullable=True)
    smtp_password = Column(String(500), nullable=True)  # Encrypted in practice
    use_tls = Column(Boolean, default=True, nullable=False)
    use_ssl = Column(Boolean, default=False, nullable=False)

    # Sender defaults
    from_email = Column(String(255), nullable=False)
    from_name = Column(String(200), default="ISP Billing Platform", nullable=False)
    reply_to_email = Column(String(255), nullable=True)

    # API Key for external providers (SendGrid, Mailgun, etc.)
    api_key = Column(String(500), nullable=True)  # Encrypted
    api_secret = Column(String(500), nullable=True)  # Encrypted

    # Additional settings (JSON for flexibility)
    additional_settings = Column(JSON, default=dict, nullable=True)

    # Rate limiting
    max_emails_per_hour = Column(Integer, default=100, nullable=True)
    max_emails_per_day = Column(Integer, default=1000, nullable=True)

    # Statistics
    total_sent = Column(Integer, default=0, nullable=False)
    total_failed = Column(Integer, default=0, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)

    # Test results
    last_test_at = Column(DateTime, nullable=True)
    last_test_success = Column(Boolean, nullable=True)
    last_test_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    verified_at = Column(DateTime, nullable=True)

    def to_dict(self, include_credentials: bool = False):
        """Convert to dictionary, optionally masking credentials."""
        data = {
            "id": self.id,
            "provider_type": self.provider_type.value if self.provider_type else None,
            "name": self.name,
            "description": self.description,
            "status": self.status.value if self.status else None,
            "is_active": self.is_active,
            "is_primary": self.is_primary,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_username": self.smtp_username,
            "use_tls": self.use_tls,
            "use_ssl": self.use_ssl,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "reply_to_email": self.reply_to_email,
            "max_emails_per_hour": self.max_emails_per_hour,
            "max_emails_per_day": self.max_emails_per_day,
            "total_sent": self.total_sent,
            "total_failed": self.total_failed,
            "last_sent_at": self.last_sent_at.isoformat() if self.last_sent_at else None,
            "last_test_at": self.last_test_at.isoformat() if self.last_test_at else None,
            "last_test_success": self.last_test_success,
            "last_test_message": self.last_test_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }

        if include_credentials:
            data["smtp_password"] = self.smtp_password
            data["api_key"] = self.api_key
            data["api_secret"] = self.api_secret
        else:
            # Mask credentials
            data["smtp_password"] = "********" if self.smtp_password else None
            data["api_key"] = "********" if self.api_key else None
            data["api_secret"] = "********" if self.api_secret else None

        return data
