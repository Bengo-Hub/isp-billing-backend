"""User interface and experience settings models."""

import json
from datetime import datetime
from enum import Enum as PyEnum
from typing import Dict, Any, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ThemeType(str, PyEnum):
    """Theme type enumeration."""
    
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"
    AUTO = "auto"


class LanguageCode(str, PyEnum):
    """Language code enumeration."""
    
    ENGLISH = "en"
    SWAHILI = "sw"
    FRENCH = "fr"
    SPANISH = "es"


class NotificationPreference(str, PyEnum):
    """Notification preference enumeration."""
    
    ALL = "all"
    IMPORTANT = "important"
    NONE = "none"


class UserSettings(Base):
    """User interface and experience settings."""

    __tablename__ = "user_settings"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    # Appearance settings
    theme = Column(Enum(ThemeType), default=ThemeType.SYSTEM, nullable=False)
    language = Column(Enum(LanguageCode), default=LanguageCode.ENGLISH, nullable=False)
    timezone = Column(String(50), default="Africa/Nairobi", nullable=False)
    date_format = Column(String(20), default="DD/MM/YYYY", nullable=False)
    time_format = Column(String(10), default="24h", nullable=False)
    currency_display = Column(String(10), default="KES", nullable=False)
    
    # Dashboard preferences
    dashboard_layout = Column(JSON, nullable=True)  # Custom dashboard layout
    default_page = Column(String(50), default="dashboard", nullable=False)
    sidebar_collapsed = Column(Boolean, default=False, nullable=False)
    show_tooltips = Column(Boolean, default=True, nullable=False)
    
    # Table and list preferences
    default_page_size = Column(Integer, default=20, nullable=False)
    show_row_numbers = Column(Boolean, default=True, nullable=False)
    enable_auto_refresh = Column(Boolean, default=True, nullable=False)
    auto_refresh_interval = Column(Integer, default=30, nullable=False)  # seconds
    
    # Notification preferences
    email_notifications = Column(Enum(NotificationPreference), default=NotificationPreference.ALL, nullable=False)
    sms_notifications = Column(Enum(NotificationPreference), default=NotificationPreference.IMPORTANT, nullable=False)
    browser_notifications = Column(Enum(NotificationPreference), default=NotificationPreference.ALL, nullable=False)
    notification_sound = Column(Boolean, default=True, nullable=False)
    
    # Security settings
    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    two_factor_method = Column(String(20), default="totp", nullable=False)  # totp, sms, email
    session_timeout_minutes = Column(Integer, default=480, nullable=False)  # 8 hours
    require_password_on_sensitive = Column(Boolean, default=True, nullable=False)
    
    # Search and filtering preferences
    saved_searches = Column(JSON, nullable=True)  # Saved search queries
    search_history = Column(JSON, nullable=True)  # Recent searches
    default_filters = Column(JSON, nullable=True)  # Default filters per page
    quick_filters = Column(JSON, nullable=True)  # User-defined quick filters
    
    # Bulk operations preferences
    bulk_operation_confirmation = Column(Boolean, default=True, nullable=False)
    max_bulk_operations = Column(Integer, default=100, nullable=False)
    bulk_operation_timeout = Column(Integer, default=300, nullable=False)  # seconds
    
    # Advanced preferences
    developer_mode = Column(Boolean, default=False, nullable=False)
    show_debug_info = Column(Boolean, default=False, nullable=False)
    enable_keyboard_shortcuts = Column(Boolean, default=True, nullable=False)
    custom_css = Column(Text, nullable=True)
    
    # Usage tracking
    last_login_ip = Column(String(45), nullable=True)
    login_count = Column(Integer, default=0, nullable=False)
    last_active = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", backref="settings")

    def __repr__(self) -> str:
        """String representation."""
        return f"<UserSettings(id={self.id}, user_id={self.user_id}, theme='{self.theme}')>"

    def get_dashboard_layout(self) -> Dict[str, Any]:
        """Get dashboard layout as dictionary."""
        return self.dashboard_layout or {}

    def set_dashboard_layout(self, layout: Dict[str, Any]) -> None:
        """Set dashboard layout from dictionary."""
        self.dashboard_layout = layout

    def get_saved_searches(self) -> List[Dict[str, Any]]:
        """Get saved searches as list."""
        return self.saved_searches or []

    def add_saved_search(self, search_data: Dict[str, Any]) -> None:
        """Add a saved search."""
        searches = self.get_saved_searches()
        searches.append({
            **search_data,
            'saved_at': datetime.utcnow().isoformat()
        })
        # Keep only last 50 searches
        self.saved_searches = searches[-50:]

    def get_search_history(self) -> List[Dict[str, Any]]:
        """Get search history as list."""
        return self.search_history or []

    def add_search_to_history(self, search_query: str, search_type: str = "global") -> None:
        """Add search to history."""
        history = self.get_search_history()
        history.append({
            'query': search_query,
            'type': search_type,
            'timestamp': datetime.utcnow().isoformat()
        })
        # Keep only last 100 searches
        self.search_history = history[-100:]

    def get_default_filters(self, page: str) -> Dict[str, Any]:
        """Get default filters for a page."""
        filters = self.default_filters or {}
        return filters.get(page, {})

    def set_default_filters(self, page: str, filters: Dict[str, Any]) -> None:
        """Set default filters for a page."""
        if self.default_filters is None:
            self.default_filters = {}
        self.default_filters[page] = filters

    def get_quick_filters(self) -> List[Dict[str, Any]]:
        """Get quick filters as list."""
        return self.quick_filters or []

    def add_quick_filter(self, filter_data: Dict[str, Any]) -> None:
        """Add a quick filter."""
        filters = self.get_quick_filters()
        filters.append({
            **filter_data,
            'created_at': datetime.utcnow().isoformat()
        })
        # Keep only last 20 quick filters
        self.quick_filters = filters[-20:]


class GlobalSearch(Base):
    """Global search functionality and indexing."""

    __tablename__ = "global_search"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Search identification
    search_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Search parameters
    query = Column(String(500), nullable=False)
    search_type = Column(String(50), default="global", nullable=False)
    filters = Column(JSON, nullable=True)
    
    # Search results
    total_results = Column(Integer, default=0, nullable=False)
    execution_time_ms = Column(Integer, nullable=False)
    results_data = Column(JSON, nullable=True)  # Cached results
    
    # Search metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # Cache expiry

    # Relationships
    user = relationship("User", backref="searches")

    def __repr__(self) -> str:
        """String representation."""
        return f"<GlobalSearch(id={self.id}, query='{self.query}', results={self.total_results})>"

    def get_results_data(self) -> List[Dict[str, Any]]:
        """Get results data as list."""
        return self.results_data or []

    def is_expired(self) -> bool:
        """Check if search results are expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at


class UIBulkOperation(Base):
    """UI bulk operations tracking and management."""

    __tablename__ = "ui_bulk_operations"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Operation identification
    operation_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Operation details
    operation_type = Column(String(50), nullable=False)  # delete, update, export, etc.
    target_model = Column(String(50), nullable=False)  # users, routers, subscriptions, etc.
    operation_data = Column(JSON, nullable=False)  # Operation parameters
    
    # Progress tracking
    status = Column(String(20), default="pending", nullable=False)
    total_items = Column(Integer, default=0, nullable=False)
    processed_items = Column(Integer, default=0, nullable=False)
    successful_items = Column(Integer, default=0, nullable=False)
    failed_items = Column(Integer, default=0, nullable=False)
    
    # Execution details
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    estimated_completion = Column(DateTime, nullable=True)
    
    # Results and errors
    results = Column(JSON, nullable=True)  # Operation results
    errors = Column(JSON, nullable=True)  # Error details
    success_rate = Column(Integer, default=0, nullable=False)  # Percentage
    
    # Metadata
    ip_address = Column(String(45), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", backref="ui_bulk_operations")

    def __repr__(self) -> str:
        """String representation."""
        return f"<UIBulkOperation(id={self.id}, type='{self.operation_type}', status='{self.status}')>"

    def get_operation_data(self) -> Dict[str, Any]:
        """Get operation data as dictionary."""
        return self.operation_data or {}

    def get_results(self) -> List[Dict[str, Any]]:
        """Get results as list."""
        return self.results or []

    def get_errors(self) -> List[Dict[str, Any]]:
        """Get errors as list."""
        return self.errors or []

    def update_progress(self, processed: int, successful: int, failed: int) -> None:
        """Update operation progress."""
        self.processed_items = processed
        self.successful_items = successful
        self.failed_items = failed
        
        if self.total_items > 0:
            self.success_rate = int((successful / processed) * 100) if processed > 0 else 0
        
        # Update status
        if processed >= self.total_items:
            self.status = "completed"
            self.completed_at = datetime.utcnow()
        elif processed > 0:
            self.status = "in_progress"

    @property
    def progress_percentage(self) -> float:
        """Get progress percentage."""
        if self.total_items <= 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100

    @property
    def is_completed(self) -> bool:
        """Check if operation is completed."""
        return self.status == "completed"

    @property
    def estimated_time_remaining(self) -> Optional[int]:
        """Estimate time remaining in seconds."""
        if not self.started_at or self.processed_items <= 0:
            return None
        
        elapsed_seconds = (datetime.utcnow() - self.started_at).total_seconds()
        avg_time_per_item = elapsed_seconds / self.processed_items
        remaining_items = self.total_items - self.processed_items
        
        return int(avg_time_per_item * remaining_items)


class SearchSuggestion(Base):
    """Search suggestions and autocomplete data."""

    __tablename__ = "search_suggestions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Suggestion details
    suggestion_text = Column(String(200), nullable=False, index=True)
    suggestion_type = Column(String(50), nullable=False)  # user, router, plan, etc.
    category = Column(String(50), nullable=True)
    
    # Usage statistics
    usage_count = Column(Integer, default=0, nullable=False)
    last_used = Column(DateTime, nullable=True)
    success_rate = Column(Integer, default=0, nullable=False)  # Percentage
    
    # Additional data
    additional_data = Column(JSON, nullable=True)  # Additional suggestion data
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<SearchSuggestion(id={self.id}, text='{self.suggestion_text}', type='{self.suggestion_type}')>"

    def increment_usage(self, was_successful: bool = True) -> None:
        """Increment usage statistics."""
        self.usage_count += 1
        self.last_used = datetime.utcnow()
        
        if was_successful:
            # Update success rate
            total_successes = int((self.success_rate / 100) * (self.usage_count - 1))
            if was_successful:
                total_successes += 1
            self.success_rate = int((total_successes / self.usage_count) * 100)


class UIPreferences(Base):
    """Global UI preferences and configuration."""

    __tablename__ = "ui_preferences"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Preference identification
    preference_key = Column(String(100), unique=True, nullable=False, index=True)
    preference_name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    
    # Preference configuration
    default_value = Column(JSON, nullable=False)
    allowed_values = Column(JSON, nullable=True)  # Allowed values for validation
    value_type = Column(String(20), nullable=False)  # string, integer, boolean, json
    
    # Preference metadata
    description = Column(Text, nullable=True)
    is_user_configurable = Column(Boolean, default=True, nullable=False)
    requires_admin = Column(Boolean, default=False, nullable=False)
    affects_security = Column(Boolean, default=False, nullable=False)
    
    # Validation rules
    validation_rules = Column(JSON, nullable=True)
    min_value = Column(Integer, nullable=True)
    max_value = Column(Integer, nullable=True)
    
    # Usage statistics
    usage_count = Column(Integer, default=0, nullable=False)
    modified_count = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<UIPreferences(id={self.id}, key='{self.preference_key}', category='{self.category}')>"

    def get_default_value(self) -> Any:
        """Get default value."""
        return self.default_value

    def get_allowed_values(self) -> List[Any]:
        """Get allowed values as list."""
        return self.allowed_values or []

    def validate_value(self, value: Any) -> bool:
        """Validate a value against preference rules."""
        # Type validation
        if self.value_type == "boolean" and not isinstance(value, bool):
            return False
        elif self.value_type == "integer" and not isinstance(value, int):
            return False
        elif self.value_type == "string" and not isinstance(value, str):
            return False
        
        # Range validation
        if self.value_type == "integer":
            if self.min_value is not None and value < self.min_value:
                return False
            if self.max_value is not None and value > self.max_value:
                return False
        
        # Allowed values validation
        if self.allowed_values and value not in self.allowed_values:
            return False
        
        return True
