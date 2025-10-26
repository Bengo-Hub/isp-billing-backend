"""Pydantic schemas for SMS Credit management APIs."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SMSCreditAccountCreate(BaseModel):
    account_name: str = Field(..., min_length=2, max_length=100)
    provider_type: str = Field(..., description="Provider identifier, e.g. africastalking|twilio|custom")
    phone_number: str = Field(..., min_length=7, max_length=20)
    country_code: str = Field("+254", min_length=2, max_length=5)
    currency: str = Field("KES", min_length=3, max_length=3)
    is_default: bool = False
    auto_top_up_enabled: bool = False
    auto_top_up_amount: Decimal = Field(0, ge=0)
    auto_top_up_threshold: Decimal = Field(0, ge=0)
    provider_config: Optional[Dict[str, Any]] = None


class SMSCreditAccountResponse(BaseModel):
    id: int
    account_name: str
    account_code: str
    provider_type: str
    phone_number: str
    country_code: str
    current_balance: Decimal
    currency: str
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SMSTopUpRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    payment_method: str = Field(..., min_length=2, max_length=50)
    sms_credits: Optional[int] = Field(None, ge=1)
    payment_reference: Optional[str] = Field(None, max_length=100)


class SMSTopUpResponse(BaseModel):
    id: int
    top_up_reference: str
    amount: Decimal
    currency: str
    sms_credits: int
    cost_per_sms: Decimal
    status: str
    requested_by: int
    processed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SMSAccountBalanceResponse(BaseModel):
    account_id: int
    account_name: str
    current_balance: float
    currency: str
    is_low_balance: bool
    minimum_threshold: float
    total_messages_sent: int
    average_cost_per_sms: float
    today_usage: Dict[str, Any]
    recent_transactions: List[Dict[str, Any]]
    auto_top_up_enabled: bool
    needs_auto_top_up: bool


class SMSTransactionItem(BaseModel):
    id: int
    transaction_id: str
    transaction_type: str
    status: str
    amount: Decimal
    currency: str
    created_at: datetime

    class Config:
        from_attributes = True


class SMSTransactionList(BaseModel):
    items: List[SMSTransactionItem]
    total: int
    page: int
    size: int
    pages: int


class SMSAnalyticsResponse(BaseModel):
    account_id: int
    period_type: str
    period_days: int
    analytics_data: List[Dict[str, Any]]
    summary: Dict[str, Any]


class ValidatePhoneRequest(BaseModel):
    phone_number: str
    country_code: str = "+254"
    validation_method: str = "sms"


class ValidatePhoneResponse(BaseModel):
    phone_number: str
    is_validated: bool
    validation_required: bool
    validation_code_sent: bool
    existing_record: bool


