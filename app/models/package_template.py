"""Advanced package management models with templates and bulk operations."""

import json
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Dict, Any, Optional, List

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class PackageCategory(str, PyEnum):
    """Package category enumeration."""
    
    HOTSPOT = "hotspot"
    PPPOE = "pppoe"
    DATA_PLANS = "data_plans"
    FREE_TRIAL = "free_trial"
    PREMIUM = "premium"
    BUSINESS = "business"
    STUDENT = "student"
    PROMOTIONAL = "promotional"


class PackageTemplateStatus(str, PyEnum):
    """Package template status enumeration."""
    
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"
    ARCHIVED = "archived"


class BulkOperationStatus(str, PyEnum):
    """Bulk operation status enumeration."""
    
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PackageTemplate(Base):
    """Package template model for quick package creation."""

    __tablename__ = "package_templates"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Template identification
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(Enum(PackageCategory), nullable=False)
    template_code = Column(String(50), unique=True, nullable=False)
    
    # Template configuration
    status = Column(Enum(PackageTemplateStatus), default=PackageTemplateStatus.ACTIVE, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    is_featured = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    
    # Package configuration template
    plan_type = Column(String(20), nullable=False)  # hotspot, pppoe, both
    price_template = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    billing_cycle = Column(String(20), default="monthly", nullable=False)
    
    # Speed and limits template
    download_speed = Column(Integer, nullable=False)  # Mbps
    upload_speed = Column(Integer, nullable=False)  # Mbps
    data_limit = Column(Integer, default=-1, nullable=False)  # GB, -1 for unlimited
    time_limit = Column(Integer, default=-1, nullable=False)  # hours, -1 for unlimited
    validity_days = Column(Integer, nullable=False)
    
    # Advanced configuration
    configuration_template = Column(JSON, nullable=True)  # Router-specific config
    features_template = Column(JSON, nullable=True)  # Available features
    restrictions_template = Column(JSON, nullable=True)  # Usage restrictions
    
    # Usage and statistics
    usage_count = Column(Integer, default=0, nullable=False)
    success_rate = Column(Numeric(5, 2), default=0, nullable=False)
    average_rating = Column(Numeric(3, 2), default=0, nullable=False)
    
    # Metadata
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    tags = Column(String(500), nullable=True)  # Comma-separated tags
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    creator = relationship("User", backref="package_templates")
    assignments = relationship("PackageAssignment", back_populates="template", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PackageTemplate(id={self.id}, name='{self.name}', category='{self.category}')>"

    def get_configuration_template(self) -> Dict[str, Any]:
        """Get configuration template as dictionary."""
        return self.configuration_template or {}

    def get_features_template(self) -> Dict[str, Any]:
        """Get features template as dictionary."""
        return self.features_template or {}

    def get_restrictions_template(self) -> Dict[str, Any]:
        """Get restrictions template as dictionary."""
        return self.restrictions_template or {}

    def get_tags_list(self) -> List[str]:
        """Get tags as list."""
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]


class PackageAssignment(Base):
    """Package assignment to MikroTik devices."""

    __tablename__ = "package_assignments"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Assignment details
    template_id = Column(Integer, ForeignKey("package_templates.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=True)  # Created plan
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False)
    
    # Assignment configuration
    assignment_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    auto_create_users = Column(Boolean, default=True, nullable=False)
    
    # Custom configuration overrides
    custom_configuration = Column(JSON, nullable=True)
    price_override = Column(Numeric(10, 2), nullable=True)
    speed_override = Column(JSON, nullable=True)  # {download: X, upload: Y}
    
    # Assignment metadata
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    assignment_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_sync_date = Column(DateTime, nullable=True)
    
    # Usage tracking
    users_created = Column(Integer, default=0, nullable=False)
    active_users = Column(Integer, default=0, nullable=False)
    total_revenue = Column(Numeric(10, 2), default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    template = relationship("PackageTemplate", back_populates="assignments")
    plan = relationship("ServicePlan", backref="package_assignments")
    router = relationship("Router", backref="package_assignments")
    assigned_by_user = relationship("User", backref="package_assignments")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PackageAssignment(id={self.id}, template_id={self.template_id}, router_id={self.router_id})>"

    def get_custom_configuration(self) -> Dict[str, Any]:
        """Get custom configuration as dictionary."""
        return self.custom_configuration or {}

    def get_effective_price(self) -> Decimal:
        """Get effective price (override or template price)."""
        if self.price_override:
            return self.price_override
        return self.template.price_template if self.template else Decimal('0')


class BulkOperation(Base):
    """Bulk operations tracking for packages and assignments."""

    __tablename__ = "bulk_operations"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Operation identification
    operation_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    operation_type = Column(String(50), nullable=False)  # create_packages, assign_packages, etc.
    operation_name = Column(String(100), nullable=False)
    
    # Operation details
    status = Column(Enum(BulkOperationStatus), default=BulkOperationStatus.PENDING, nullable=False)
    total_items = Column(Integer, nullable=False)
    processed_items = Column(Integer, default=0, nullable=False)
    successful_items = Column(Integer, default=0, nullable=False)
    failed_items = Column(Integer, default=0, nullable=False)
    
    # Operation data
    operation_data = Column(JSON, nullable=False)  # Input data for operation
    results_data = Column(JSON, nullable=True)  # Results and errors
    
    # Progress tracking
    progress_percentage = Column(Numeric(5, 2), default=0, nullable=False)
    current_item = Column(String(200), nullable=True)
    
    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    estimated_completion = Column(DateTime, nullable=True)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    can_retry = Column(Boolean, default=True, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    
    # Metadata
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    creator = relationship("User", backref="bulk_operations")

    def __repr__(self) -> str:
        """String representation."""
        return f"<BulkOperation(id={self.id}, type='{self.operation_type}', status='{self.status}')>"

    def get_operation_data(self) -> Dict[str, Any]:
        """Get operation data as dictionary."""
        return self.operation_data or {}

    def get_results_data(self) -> Dict[str, Any]:
        """Get results data as dictionary."""
        return self.results_data or {}

    def add_result(self, item_id: str, success: bool, data: Any = None, error: str = None) -> None:
        """Add result for a processed item."""
        if not self.results_data:
            self.results_data = {"items": []}
        
        self.results_data["items"].append({
            "item_id": item_id,
            "success": success,
            "data": data,
            "error": error,
            "processed_at": datetime.utcnow().isoformat()
        })

    def update_progress(self, processed: int, successful: int, failed: int, current_item: str = None) -> None:
        """Update operation progress."""
        self.processed_items = processed
        self.successful_items = successful
        self.failed_items = failed
        self.progress_percentage = (processed / self.total_items * 100) if self.total_items > 0 else 0
        if current_item:
            self.current_item = current_item


class PackageGuide(Base):
    """Package setup guides and documentation."""

    __tablename__ = "package_guides"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Guide identification
    title = Column(String(200), nullable=False)
    category = Column(Enum(PackageCategory), nullable=False)
    guide_type = Column(String(50), nullable=False)  # setup, troubleshooting, best_practices
    
    # Guide content
    content = Column(Text, nullable=False)  # Markdown content
    steps = Column(JSON, nullable=True)  # Step-by-step instructions
    examples = Column(JSON, nullable=True)  # Example configurations
    
    # Guide metadata
    difficulty_level = Column(String(20), default="beginner", nullable=False)  # beginner, intermediate, advanced
    estimated_time_minutes = Column(Integer, default=10, nullable=False)
    prerequisites = Column(JSON, nullable=True)  # Required knowledge/setup
    
    # Visibility and access
    is_published = Column(Boolean, default=True, nullable=False)
    is_featured = Column(Boolean, default=False, nullable=False)
    access_level = Column(String(20), default="public", nullable=False)  # public, premium, admin
    
    # Usage statistics
    view_count = Column(Integer, default=0, nullable=False)
    helpful_votes = Column(Integer, default=0, nullable=False)
    total_votes = Column(Integer, default=0, nullable=False)
    
    # Versioning
    version = Column(String(20), default="1.0", nullable=False)
    parent_guide_id = Column(Integer, ForeignKey("package_guides.id"), nullable=True)
    
    # Author information
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    last_updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    published_at = Column(DateTime, nullable=True)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by], backref="created_guides")
    updater = relationship("User", foreign_keys=[last_updated_by], backref="updated_guides")
    parent_guide = relationship("PackageGuide", remote_side="PackageGuide.id", backref="child_guides")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PackageGuide(id={self.id}, title='{self.title}', category='{self.category}')>"

    def get_steps(self) -> List[Dict[str, Any]]:
        """Get steps as list."""
        return self.steps or []

    def get_examples(self) -> List[Dict[str, Any]]:
        """Get examples as list."""
        return self.examples or []

    def get_prerequisites(self) -> List[str]:
        """Get prerequisites as list."""
        return self.prerequisites or []

    @property
    def helpfulness_percentage(self) -> float:
        """Calculate helpfulness percentage."""
        if self.total_votes == 0:
            return 0.0
        return (self.helpful_votes / self.total_votes) * 100


class QuickSetup(Base):
    """Quick setup configurations for common package scenarios."""

    __tablename__ = "quick_setups"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Setup identification
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    scenario = Column(String(100), nullable=False)  # new_isp, expansion, migration, etc.
    
    # Setup configuration
    packages_config = Column(JSON, nullable=False)  # Package configurations to create
    router_config = Column(JSON, nullable=True)  # Router configuration requirements
    recommended_order = Column(JSON, nullable=True)  # Recommended setup order
    
    # Setup metadata
    difficulty_level = Column(String(20), default="beginner", nullable=False)
    estimated_time_minutes = Column(Integer, default=30, nullable=False)
    target_user_count = Column(Integer, nullable=True)  # Target number of users
    
    # Visibility
    is_active = Column(Boolean, default=True, nullable=False)
    is_recommended = Column(Boolean, default=False, nullable=False)
    
    # Usage statistics
    usage_count = Column(Integer, default=0, nullable=False)
    success_rate = Column(Numeric(5, 2), default=0, nullable=False)
    
    # Author information
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    creator = relationship("User", backref="quick_setups")

    def __repr__(self) -> str:
        """String representation."""
        return f"<QuickSetup(id={self.id}, name='{self.name}', scenario='{self.scenario}')>"

    def get_packages_config(self) -> List[Dict[str, Any]]:
        """Get packages configuration as list."""
        return self.packages_config or []

    def get_router_config(self) -> Dict[str, Any]:
        """Get router configuration as dictionary."""
        return self.router_config or {}

    def get_recommended_order(self) -> List[str]:
        """Get recommended setup order as list."""
        return self.recommended_order or []


class PackageCategoryConfig(Base):
    """Configuration for package categories."""

    __tablename__ = "package_category_configs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Category details
    category = Column(Enum(PackageCategory), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)
    color = Column(String(7), nullable=True)  # Hex color code
    
    # Category configuration
    default_billing_cycle = Column(String(20), default="monthly", nullable=False)
    default_validity_days = Column(Integer, default=30, nullable=False)
    supports_hotspot = Column(Boolean, default=True, nullable=False)
    supports_pppoe = Column(Boolean, default=True, nullable=False)
    
    # Pricing configuration
    min_price = Column(Numeric(10, 2), default=0, nullable=False)
    max_price = Column(Numeric(10, 2), nullable=True)
    suggested_prices = Column(JSON, nullable=True)  # Array of suggested price points
    
    # Feature configuration
    default_features = Column(JSON, nullable=True)
    required_features = Column(JSON, nullable=True)
    optional_features = Column(JSON, nullable=True)
    
    # Display configuration
    is_visible = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    show_in_public = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<PackageCategoryConfig(id={self.id}, category='{self.category}', name='{self.display_name}')>"

    def get_default_features(self) -> Dict[str, Any]:
        """Get default features as dictionary."""
        return self.default_features or {}

    def get_suggested_prices(self) -> List[Decimal]:
        """Get suggested prices as list."""
        if not self.suggested_prices:
            return []
        return [Decimal(str(price)) for price in self.suggested_prices]


class PackageRating(Base):
    """Package template ratings and reviews."""

    __tablename__ = "package_ratings"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Rating details
    template_id = Column(Integer, ForeignKey("package_templates.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Rating data
    rating = Column(Integer, nullable=False)  # 1-5 stars
    review = Column(Text, nullable=True)
    is_helpful = Column(Boolean, nullable=True)
    
    # Usage context
    use_case = Column(String(100), nullable=True)
    router_model = Column(String(50), nullable=True)
    user_count = Column(Integer, nullable=True)
    
    # Moderation
    is_approved = Column(Boolean, default=True, nullable=False)
    is_featured = Column(Boolean, default=False, nullable=False)
    moderated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    moderated_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    template = relationship("PackageTemplate", backref="ratings")
    user = relationship("User", foreign_keys=[user_id], backref="package_ratings")
    moderator = relationship("User", foreign_keys=[moderated_by], backref="moderated_ratings")

    # Constraints
    __table_args__ = (
        UniqueConstraint('template_id', 'user_id', name='uq_template_user_rating'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<PackageRating(id={self.id}, template_id={self.template_id}, rating={self.rating})>"
