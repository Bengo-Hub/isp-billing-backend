"""UI/UX management schemas for request/response validation."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.user_settings import ThemeType, LanguageCode, NotificationPreference


# User Settings Schemas
class UserSettingsBase(BaseModel):
    """Base user settings schema."""
    
    theme: ThemeType = ThemeType.SYSTEM
    language: LanguageCode = LanguageCode.ENGLISH
    timezone: str = Field("Africa/Nairobi", max_length=50)
    date_format: str = Field("DD/MM/YYYY", max_length=20)
    time_format: str = Field("24h", max_length=10)
    currency_display: str = Field("KES", max_length=10)
    default_page_size: int = Field(20, ge=5, le=100)
    sidebar_collapsed: bool = False
    show_tooltips: bool = True
    enable_auto_refresh: bool = True
    auto_refresh_interval: int = Field(30, ge=10, le=300)
    email_notifications: NotificationPreference = NotificationPreference.ALL
    sms_notifications: NotificationPreference = NotificationPreference.IMPORTANT
    browser_notifications: NotificationPreference = NotificationPreference.ALL
    notification_sound: bool = True
    two_factor_enabled: bool = False
    two_factor_method: str = Field("totp", max_length=20)
    session_timeout_minutes: int = Field(480, ge=30, le=1440)
    require_password_on_sensitive: bool = True
    bulk_operation_confirmation: bool = True
    max_bulk_operations: int = Field(100, ge=10, le=1000)
    developer_mode: bool = False
    show_debug_info: bool = False
    enable_keyboard_shortcuts: bool = True


class UserSettingsCreate(UserSettingsBase):
    """User settings creation schema."""
    
    user_id: int


class UserSettingsUpdate(BaseModel):
    """User settings update schema."""
    
    theme: Optional[ThemeType] = None
    language: Optional[LanguageCode] = None
    timezone: Optional[str] = Field(None, max_length=50)
    date_format: Optional[str] = Field(None, max_length=20)
    time_format: Optional[str] = Field(None, max_length=10)
    currency_display: Optional[str] = Field(None, max_length=10)
    default_page_size: Optional[int] = Field(None, ge=5, le=100)
    sidebar_collapsed: Optional[bool] = None
    show_tooltips: Optional[bool] = None
    enable_auto_refresh: Optional[bool] = None
    auto_refresh_interval: Optional[int] = Field(None, ge=10, le=300)
    email_notifications: Optional[NotificationPreference] = None
    sms_notifications: Optional[NotificationPreference] = None
    browser_notifications: Optional[NotificationPreference] = None
    notification_sound: Optional[bool] = None
    two_factor_enabled: Optional[bool] = None
    two_factor_method: Optional[str] = Field(None, max_length=20)
    session_timeout_minutes: Optional[int] = Field(None, ge=30, le=1440)
    require_password_on_sensitive: Optional[bool] = None
    bulk_operation_confirmation: Optional[bool] = None
    max_bulk_operations: Optional[int] = Field(None, ge=10, le=1000)
    developer_mode: Optional[bool] = None
    show_debug_info: Optional[bool] = None
    enable_keyboard_shortcuts: Optional[bool] = None
    dashboard_layout: Optional[Dict[str, Any]] = None
    saved_searches: Optional[List[Dict[str, Any]]] = None
    default_filters: Optional[Dict[str, Any]] = None
    quick_filters: Optional[List[Dict[str, Any]]] = None


class UserSettings(UserSettingsBase):
    """User settings response schema."""
    
    id: int
    user_id: int
    dashboard_layout: Optional[Dict[str, Any]]
    saved_searches: Optional[List[Dict[str, Any]]]
    search_history: Optional[List[Dict[str, Any]]]
    default_filters: Optional[Dict[str, Any]]
    quick_filters: Optional[List[Dict[str, Any]]]
    last_login_ip: Optional[str]
    login_count: int
    last_active: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Global Search Schemas
class GlobalSearchRequest(BaseModel):
    """Global search request schema."""
    
    query: str = Field(..., min_length=2, max_length=500)
    search_types: Optional[List[str]] = Field(None, description="Types to search: users, routers, plans, etc.")
    filters: Optional[Dict[str, Any]] = Field(None, description="Additional filters")
    limit: int = Field(50, ge=1, le=100)
    include_suggestions: bool = True

    @field_validator('query')
    @classmethod
    def validate_query(cls, v):
        """Validate search query."""
        if not v or len(v.strip()) < 2:
            raise ValueError("Search query must be at least 2 characters")
        return v.strip()


class GlobalSearchResponse(BaseModel):
    """Global search response schema."""
    
    search_id: str
    query: str
    total_results: int
    execution_time_ms: int
    results: Dict[str, List[Dict[str, Any]]]
    search_types: List[str]
    suggestions: Optional[List[Dict[str, Any]]] = None


class SearchSuggestionResponse(BaseModel):
    """Search suggestion response schema."""
    
    text: str
    type: str
    category: Optional[str]
    usage_count: int
    success_rate: int


# Bulk Operations Schemas
class BulkOperationRequest(BaseModel):
    """Bulk operation request schema."""
    
    operation_type: str = Field(..., description="Operation type: delete, update, export")
    target_model: str = Field(..., description="Target model: users, routers, plans, etc.")
    target_ids: List[int] = Field(..., min_items=1, max_items=1000)
    operation_data: Optional[Dict[str, Any]] = Field(None, description="Operation-specific data")
    confirm_operation: bool = Field(False, description="Confirmation flag for destructive operations")

    @field_validator('target_ids')
    @classmethod
    def validate_target_ids(cls, v):
        """Validate target IDs."""
        if not v or len(v) == 0:
            raise ValueError("At least one target ID is required")
        if len(v) > 1000:
            raise ValueError("Maximum 1000 items allowed in bulk operation")
        return v

    @field_validator('operation_type')
    @classmethod
    def validate_operation_type(cls, v):
        """Validate operation type."""
        allowed_types = ['delete', 'update', 'export', 'activate', 'deactivate', 'suspend', 'resume']
        if v not in allowed_types:
            raise ValueError(f"Operation type must be one of: {', '.join(allowed_types)}")
        return v


class BulkOperationResponse(BaseModel):
    """Bulk operation response schema."""
    
    operation_id: str
    status: str
    operation_type: str
    target_model: str
    total_items: int
    processed_items: int
    successful_items: int
    failed_items: int
    progress_percentage: float
    success_rate: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    estimated_time_remaining: Optional[int]
    errors: List[Dict[str, Any]]


class BulkOperationStatus(BaseModel):
    """Bulk operation status schema."""
    
    operation_id: str
    status: str
    progress_percentage: float
    current_item: Optional[str]
    estimated_time_remaining: Optional[int]
    can_cancel: bool


# Theme and Appearance Schemas
class ThemeOption(BaseModel):
    """Theme option schema."""
    
    value: str
    label: str
    description: str
    preview_colors: Optional[Dict[str, str]] = None


class LanguageOption(BaseModel):
    """Language option schema."""
    
    value: str
    label: str
    native: str
    flag: Optional[str] = None


# UI Preferences Schemas
class UIPreferenceUpdate(BaseModel):
    """UI preference update schema."""
    
    preference_key: str
    value: Any
    
    @field_validator('preference_key')
    @classmethod
    def validate_preference_key(cls, v):
        """Validate preference key format."""
        if not v or len(v) < 3:
            raise ValueError("Preference key must be at least 3 characters")
        return v


class UIPreferenceResponse(BaseModel):
    """UI preference response schema."""
    
    preference_key: str
    preference_name: str
    category: str
    current_value: Any
    default_value: Any
    allowed_values: Optional[List[Any]]
    value_type: str
    description: Optional[str]
    is_user_configurable: bool
    requires_admin: bool


# Dashboard and Layout Schemas
class DashboardLayoutUpdate(BaseModel):
    """Dashboard layout update schema."""
    
    layout: Dict[str, Any] = Field(..., description="Dashboard layout configuration")
    
    @field_validator('layout')
    @classmethod
    def validate_layout(cls, v):
        """Validate dashboard layout structure."""
        if not isinstance(v, dict):
            raise ValueError("Layout must be a dictionary")
        
        # Basic validation - can be extended
        required_fields = ['widgets', 'columns']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Layout missing required field: {field}")
        
        return v


# Search and Filter Schemas
class SavedSearchCreate(BaseModel):
    """Saved search creation schema."""
    
    name: str = Field(..., min_length=1, max_length=100)
    query: str = Field(..., min_length=2, max_length=500)
    search_type: str = Field(..., max_length=50)
    filters: Optional[Dict[str, Any]] = None
    description: Optional[str] = Field(None, max_length=200)


class SavedSearchResponse(BaseModel):
    """Saved search response schema."""
    
    name: str
    query: str
    search_type: str
    filters: Optional[Dict[str, Any]]
    description: Optional[str]
    saved_at: str
    usage_count: int = 0


class QuickFilterCreate(BaseModel):
    """Quick filter creation schema."""
    
    name: str = Field(..., min_length=1, max_length=50)
    page: str = Field(..., max_length=50)
    filters: Dict[str, Any] = Field(..., description="Filter configuration")
    icon: Optional[str] = Field(None, max_length=20)
    color: Optional[str] = Field(None, max_length=7)  # Hex color


class QuickFilterResponse(BaseModel):
    """Quick filter response schema."""
    
    name: str
    page: str
    filters: Dict[str, Any]
    icon: Optional[str]
    color: Optional[str]
    created_at: str
    usage_count: int = 0


# Statistics Schemas
class UIUsageStats(BaseModel):
    """UI usage statistics schema."""
    
    period_days: int
    search_statistics: Dict[str, Any]
    bulk_operation_statistics: Dict[str, Any]
    theme_usage: Dict[str, int]
    generated_at: str
