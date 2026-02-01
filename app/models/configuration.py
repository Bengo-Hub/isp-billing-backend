"""Configuration model for storing application settings."""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class ConfigType(str, enum.Enum):
    """Configuration value types."""
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    JSON = "json"
    ENCRYPTED = "encrypted"


class Configuration(Base):
    """Configuration settings stored in database."""

    __tablename__ = "configurations"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True)
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text, nullable=True) # Plain text value
    encrypted_value = Column(Text, nullable=True) # Encrypted value if is_encrypted is True
    config_type = Column(Enum(ConfigType), default=ConfigType.STRING, nullable=False)
    description = Column(Text, nullable=True)
    is_encrypted = Column(Boolean, default=False, nullable=False)
    is_sensitive = Column(Boolean, default=False, nullable=False)
    category = Column(String(100), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<Configuration(key='{self.key}', type='{self.config_type}')>"
