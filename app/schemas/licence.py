"""Licence management schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.licence import LicenceStatus, LicenceType, LicencePaymentStatus


# Base schemas
class LicenceBase(BaseModel):
    """Base licence schema."""
    
    licence_name: str = Field(..., max_length=100)
    licence_type: LicenceType
    organization_name: Optional[str] = Field(None, max_length=200)
    contact_email: str = Field(..., max_length=100)
    contact_phone: Optional[str] = Field(None, max_length=20)
    max_routers: int = Field(1, ge=1)
    max_users: int = Field(100, ge=1)
    max_concurrent_sessions: int = Field(50, ge=1)
    monthly_cost: Decimal = Field(..., ge=0)
    currency: str = Field("USD", max_length=3)
    billing_cycle_months: int = Field(1, ge=1, le=12)
    features: Optional[Dict[str, Any]] = None
    auto_renewal_enabled: bool = True
    renewal_reminder_days: int = Field(7, ge=1, le=30)
    notes: Optional[str] = None

    @field_validator('contact_email')
    @classmethod
    def validate_email(cls, v):
        """Validate email format."""
        import re
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email format')
        return v

    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v):
        """Validate currency code."""
        valid_currencies = ['USD', 'KES', 'EUR', 'GBP']
        if v.upper() not in valid_currencies:
            raise ValueError(f'Currency must be one of: {", ".join(valid_currencies)}')
        return v.upper()


class LicenceCreate(LicenceBase):
    """Licence creation schema."""
    
    expiry_date: datetime
    issue_date: Optional[datetime] = None

    @field_validator('expiry_date')
    @classmethod
    def validate_expiry_date(cls, v):
        """Validate expiry date is in the future."""
        if v <= datetime.utcnow():
            raise ValueError('Expiry date must be in the future')
        return v


class LicenceUpdate(BaseModel):
    """Licence update schema."""
    
    licence_name: Optional[str] = Field(None, max_length=100)
    status: Optional[LicenceStatus] = None
    expiry_date: Optional[datetime] = None
    organization_name: Optional[str] = Field(None, max_length=200)
    contact_email: Optional[str] = Field(None, max_length=100)
    contact_phone: Optional[str] = Field(None, max_length=20)
    max_routers: Optional[int] = Field(None, ge=1)
    max_users: Optional[int] = Field(None, ge=1)
    max_concurrent_sessions: Optional[int] = Field(None, ge=1)
    monthly_cost: Optional[Decimal] = Field(None, ge=0)
    features: Optional[Dict[str, Any]] = None
    auto_renewal_enabled: Optional[bool] = None
    renewal_reminder_days: Optional[int] = Field(None, ge=1, le=30)
    notes: Optional[str] = None


class Licence(LicenceBase):
    """Licence response schema."""
    
    id: int
    licence_key: str
    status: LicenceStatus
    issue_date: datetime
    expiry_date: datetime
    last_renewal_date: Optional[datetime]
    current_routers: int
    current_users: int
    total_transactions: int
    created_at: datetime
    updated_at: datetime
    
    # Computed properties
    is_expired: bool
    days_until_expiry: int
    is_near_expiry: bool

    class Config:
        from_attributes = True


class LicenceList(BaseModel):
    """Licence list response."""
    
    items: List[Licence]
    total: int
    page: int
    size: int
    pages: int


# Payment schemas
class LicencePaymentBase(BaseModel):
    """Base licence payment schema."""
    
    amount: Decimal = Field(..., ge=0)
    currency: str = Field("USD", max_length=3)
    payment_method: str = Field(..., max_length=50)
    billing_period_start: datetime
    billing_period_end: datetime
    is_renewal: bool = False
    is_upgrade: bool = False
    invoice_number: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class LicencePaymentCreate(LicencePaymentBase):
    """Licence payment creation schema."""
    
    licence_id: int
    external_transaction_id: Optional[str] = Field(None, max_length=100)


class LicencePaymentUpdate(BaseModel):
    """Licence payment update schema."""
    
    status: Optional[LicencePaymentStatus] = None
    payment_date: Optional[datetime] = None
    processed_date: Optional[datetime] = None
    external_transaction_id: Optional[str] = Field(None, max_length=100)
    gateway_response: Optional[str] = None
    extends_licence_until: Optional[datetime] = None
    notes: Optional[str] = None


class LicencePayment(LicencePaymentBase):
    """Licence payment response schema."""
    
    id: int
    licence_id: int
    payment_reference: str
    status: LicencePaymentStatus
    payment_date: Optional[datetime]
    processed_date: Optional[datetime]
    external_transaction_id: Optional[str]
    extends_licence_until: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LicencePaymentList(BaseModel):
    """Licence payment list response."""
    
    items: List[LicencePayment]
    total: int
    page: int
    size: int
    pages: int


# Usage log schemas
class LicenceUsageLogBase(BaseModel):
    """Base licence usage log schema."""
    
    routers_count: int = Field(0, ge=0)
    users_count: int = Field(0, ge=0)
    active_sessions: int = Field(0, ge=0)
    total_transactions: int = Field(0, ge=0)
    data_transferred_gb: Decimal = Field(0, ge=0)
    daily_revenue: Decimal = Field(0, ge=0)
    monthly_revenue: Decimal = Field(0, ge=0)
    sms_balance: Decimal = Field(0, ge=0)
    system_uptime_percentage: Decimal = Field(0, ge=0, le=100)
    average_response_time_ms: int = Field(0, ge=0)
    error_rate_percentage: Decimal = Field(0, ge=0, le=100)
    features_used: Optional[Dict[str, Any]] = None
    api_calls_count: int = Field(0, ge=0)


class LicenceUsageLogCreate(LicenceUsageLogBase):
    """Licence usage log creation schema."""
    
    licence_id: int
    log_date: datetime
    log_type: str = Field("daily", pattern="^(daily|weekly|monthly)$")


class LicenceUsageLog(LicenceUsageLogBase):
    """Licence usage log response schema."""
    
    id: int
    licence_id: int
    log_date: datetime
    log_type: str
    created_at: datetime

    class Config:
        from_attributes = True


# Analytics schemas
class LicenceAnalytics(BaseModel):
    """Licence analytics response."""
    
    licence_id: int
    current_status: LicenceStatus
    days_until_expiry: int
    usage_statistics: Dict[str, Any]
    revenue_metrics: Dict[str, Any]
    performance_metrics: Dict[str, Any]
    feature_usage: Dict[str, Any]
    alerts: List[Dict[str, Any]]
    recommendations: List[str]


class LicenceEarningsResponse(BaseModel):
    """Licence earnings response."""
    
    licence_id: int
    period_type: str  # daily, weekly, monthly
    earnings_data: List[Dict[str, Any]]
    total_revenue: Decimal
    total_transactions: int
    average_transaction_value: Decimal
    growth_percentage: Optional[float] = None


class LicenceRenewalRequest(BaseModel):
    """Licence renewal request."""
    
    licence_id: int
    renewal_months: int = Field(1, ge=1, le=24)
    payment_method: str
    auto_renewal: bool = True
    upgrade_type: Optional[LicenceType] = None


class LicenceRenewalResponse(BaseModel):
    """Licence renewal response."""
    
    licence_id: int
    payment_reference: str
    renewal_amount: Decimal
    new_expiry_date: datetime
    payment_url: Optional[str] = None
    instructions: str


# Dashboard schemas
class LicenceDashboard(BaseModel):
    """Licence dashboard data."""
    
    licence_summary: Licence
    usage_overview: Dict[str, Any]
    recent_payments: List[LicencePayment]
    active_alerts: List[Dict[str, Any]]
    earnings_summary: Dict[str, Any]
    system_health: Dict[str, Any]
    quick_actions: List[Dict[str, str]]


class LicenceStatusCheck(BaseModel):
    """Licence status check response."""
    
    licence_key: str
    status: LicenceStatus
    is_valid: bool
    expiry_date: datetime
    days_remaining: int
    features_available: List[str]
    usage_limits: Dict[str, Any]
    current_usage: Dict[str, Any]
    warnings: List[str]
    errors: List[str]
