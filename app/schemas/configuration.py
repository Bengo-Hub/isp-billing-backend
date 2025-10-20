"""Configuration schemas."""

from typing import Any, Optional
from pydantic import BaseModel, Field
from app.models.configuration import ConfigType


class ConfigurationBase(BaseModel):
    """Base configuration schema."""
    key: str = Field(..., description="Configuration key")
    value: Any = Field(..., description="Configuration value")
    config_type: ConfigType = Field(ConfigType.STRING, description="Configuration type")
    description: Optional[str] = Field(None, description="Configuration description")
    is_encrypted: bool = Field(False, description="Whether the value is encrypted")
    is_sensitive: bool = Field(False, description="Whether the value is sensitive")
    category: Optional[str] = Field(None, description="Configuration category")


class ConfigurationCreate(ConfigurationBase):
    """Schema for creating configuration."""
    pass


class ConfigurationUpdate(BaseModel):
    """Schema for updating configuration."""
    value: Optional[Any] = Field(None, description="Configuration value")
    config_type: Optional[ConfigType] = Field(None, description="Configuration type")
    description: Optional[str] = Field(None, description="Configuration description")
    is_encrypted: Optional[bool] = Field(None, description="Whether the value is encrypted")
    is_sensitive: Optional[bool] = Field(None, description="Whether the value is sensitive")
    category: Optional[str] = Field(None, description="Configuration category")


class ConfigurationResponse(ConfigurationBase):
    """Schema for configuration response."""
    id: int = Field(..., description="Configuration ID")
    is_active: bool = Field(..., description="Whether the configuration is active")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    class Config:
        from_attributes = True


class ConfigurationList(BaseModel):
    """Schema for configuration list response."""
    configurations: list[ConfigurationResponse] = Field(..., description="List of configurations")
    total: int = Field(..., description="Total number of configurations")
