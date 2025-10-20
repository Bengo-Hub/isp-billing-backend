"""Service plan-related Pydantic schemas."""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.plan import PlanType, PlanStatus, BillingCycle


class PlanFeatureBase(BaseModel):
    """Base plan feature schema."""

    feature_name: str = Field(..., min_length=1, max_length=100)
    feature_value: Optional[str] = Field(None, max_length=255)
    is_included: bool = True
    sort_order: int = 0


class PlanFeatureCreate(PlanFeatureBase):
    """Schema for creating a plan feature."""
    pass


class PlanFeatureUpdate(BaseModel):
    """Schema for updating a plan feature."""

    feature_name: Optional[str] = Field(None, min_length=1, max_length=100)
    feature_value: Optional[str] = Field(None, max_length=255)
    is_included: Optional[bool] = None
    sort_order: Optional[int] = None


class PlanFeature(PlanFeatureBase):
    """Schema for plan feature response."""

    id: int
    plan_id: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class PlanPricingBase(BaseModel):
    """Base plan pricing schema."""

    duration_months: int = Field(..., ge=1, le=60)
    price: Decimal = Field(..., ge=0)
    discount_percentage: Decimal = Field(0, ge=0, le=100)


class PlanPricingCreate(PlanPricingBase):
    """Schema for creating plan pricing."""
    pass


class PlanPricingUpdate(BaseModel):
    """Schema for updating plan pricing."""

    duration_months: Optional[int] = Field(None, ge=1, le=60)
    price: Optional[Decimal] = Field(None, ge=0)
    discount_percentage: Optional[Decimal] = Field(None, ge=0, le=100)


class PlanPricing(PlanPricingBase):
    """Schema for plan pricing response."""

    id: int
    plan_id: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ServicePlanBase(BaseModel):
    """Base service plan schema."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    plan_type: PlanType = PlanType.INTERNET
    price: Decimal = Field(..., ge=0)
    currency: str = Field("KES", min_length=3, max_length=3)
    billing_cycle: BillingCycle = BillingCycle.MONTHLY
    download_speed: int = Field(..., ge=0)
    upload_speed: int = Field(..., ge=0)
    data_limit: int = Field(-1, ge=-1)  # -1 for unlimited
    time_limit: int = Field(-1, ge=-1)  # -1 for unlimited
    validity_days: int = Field(..., ge=1)
    fup_enabled: bool = False
    fup_threshold: Optional[int] = Field(None, ge=0)
    fup_download_speed: Optional[int] = Field(None, ge=0)
    fup_upload_speed: Optional[int] = Field(None, ge=0)
    concurrent_sessions: int = Field(1, ge=1)
    auto_renewal: bool = False
    is_popular: bool = False
    sort_order: int = 0
    config: Optional[str] = None
    notes: Optional[str] = None

    @validator("currency")
    def validate_currency(cls, v):
        """Validate currency code."""
        if len(v) != 3:
            raise ValueError("Currency code must be 3 characters")
        return v.upper()

    @validator("fup_threshold")
    def validate_fup_threshold(cls, v, values):
        """Validate FUP threshold."""
        if values.get("fup_enabled") and v is None:
            raise ValueError("FUP threshold is required when FUP is enabled")
        return v

    @validator("fup_download_speed")
    def validate_fup_download_speed(cls, v, values):
        """Validate FUP download speed."""
        if values.get("fup_enabled") and v is None:
            raise ValueError("FUP download speed is required when FUP is enabled")
        return v

    @validator("fup_upload_speed")
    def validate_fup_upload_speed(cls, v, values):
        """Validate FUP upload speed."""
        if values.get("fup_enabled") and v is None:
            raise ValueError("FUP upload speed is required when FUP is enabled")
        return v


class ServicePlanCreate(ServicePlanBase):
    """Schema for creating a service plan."""
    pass


class ServicePlanUpdate(BaseModel):
    """Schema for updating a service plan."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    plan_type: Optional[PlanType] = None
    price: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    billing_cycle: Optional[BillingCycle] = None
    download_speed: Optional[int] = Field(None, ge=0)
    upload_speed: Optional[int] = Field(None, ge=0)
    data_limit: Optional[int] = Field(None, ge=-1)
    time_limit: Optional[int] = Field(None, ge=-1)
    validity_days: Optional[int] = Field(None, ge=1)
    fup_enabled: Optional[bool] = None
    fup_threshold: Optional[int] = Field(None, ge=0)
    fup_download_speed: Optional[int] = Field(None, ge=0)
    fup_upload_speed: Optional[int] = Field(None, ge=0)
    concurrent_sessions: Optional[int] = Field(None, ge=1)
    auto_renewal: Optional[bool] = None
    is_popular: Optional[bool] = None
    sort_order: Optional[int] = None
    config: Optional[str] = None
    notes: Optional[str] = None

    @validator("currency")
    def validate_currency(cls, v):
        """Validate currency code."""
        if v and len(v) != 3:
            raise ValueError("Currency code must be 3 characters")
        return v.upper() if v else v


class ServicePlanInDB(ServicePlanBase):
    """Schema for service plan in database."""

    id: int
    status: PlanStatus
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ServicePlan(ServicePlanInDB):
    """Schema for service plan response."""

    features: List[PlanFeature] = []
    pricing: List[PlanPricing] = []


class ServicePlanStats(BaseModel):
    """Schema for service plan statistics."""

    plan_id: int
    plan_name: str
    total_subscriptions: int
    active_subscriptions: int
    inactive_subscriptions: int
    revenue: float


class ServicePlanList(BaseModel):
    """Schema for service plan list response."""

    plans: List[ServicePlan]
    total: int
    page: int
    size: int
    pages: int


class ServicePlanFilter(BaseModel):
    """Schema for service plan filters."""

    plan_type: Optional[PlanType] = None
    status: Optional[PlanStatus] = None
    is_active: Optional[bool] = None
    search: Optional[str] = None
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    min_speed: Optional[int] = None
    max_speed: Optional[int] = None
