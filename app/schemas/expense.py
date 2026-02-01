"""Expense tracking Pydantic schemas."""

from datetime import date as Date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.expense import ExpenseStatus, ExpenseCategory


class ExpenseBase(BaseModel):
    """Base expense schema."""

    date: Date = Field(..., description="Date of the expense")
    category: ExpenseCategory = Field(..., description="Expense category")
    description: str = Field(..., min_length=1, max_length=1000, description="Expense description")
    amount: Decimal = Field(..., gt=0, description="Expense amount")
    currency: str = Field("KES", max_length=3, description="Currency code")
    receipt_url: Optional[str] = Field(None, max_length=500, description="URL to receipt/proof")
    notes: Optional[str] = Field(None, description="Additional notes")


class ExpenseCreate(ExpenseBase):
    """Schema for creating an expense."""
    pass


class ExpenseUpdate(BaseModel):
    """Schema for updating an expense."""

    date: Optional[Date] = None
    category: Optional[ExpenseCategory] = None
    description: Optional[str] = Field(None, min_length=1, max_length=1000)
    amount: Optional[Decimal] = Field(None, gt=0)
    currency: Optional[str] = Field(None, max_length=3)
    receipt_url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None


class ExpenseApprove(BaseModel):
    """Schema for approving an expense."""
    pass


class ExpenseReject(BaseModel):
    """Schema for rejecting an expense."""

    rejection_reason: str = Field(..., min_length=1, max_length=500, description="Reason for rejection")


class Expense(ExpenseBase):
    """Schema for expense response."""

    id: int
    organization_id: int
    added_by_user_id: int
    status: ExpenseStatus
    approved_by_user_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ExpenseListResponse(BaseModel):
    """Schema for paginated expense list response."""

    items: list[Expense]
    total: int
    page: int
    size: int
    pages: int

    class Config:
        from_attributes = True


class ExpenseStats(BaseModel):
    """Schema for expense statistics."""

    total_expenses: int
    approved_expenses: int
    pending_expenses: int
    rejected_expenses: int
    total_amount: Decimal
    daily_expenses: Decimal
    monthly_expenses: Decimal
    by_category: dict[str, Decimal]

    class Config:
        from_attributes = True
