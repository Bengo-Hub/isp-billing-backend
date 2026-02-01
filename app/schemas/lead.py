"""Lead Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, EmailStr

from app.models.lead import LeadStatus, LeadSource


class LeadBase(BaseModel):
    """Base lead schema."""

    name: str = Field(..., min_length=1, max_length=200, description="Lead name")
    email: Optional[EmailStr] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, max_length=20, description="Phone number")
    company: Optional[str] = Field(None, max_length=200, description="Company name")
    address: Optional[str] = Field(None, description="Address")
    city: Optional[str] = Field(None, max_length=100, description="City")
    source: Optional[LeadSource] = Field(None, description="Lead source")
    notes: Optional[str] = Field(None, description="Notes")
    estimated_value: Optional[int] = Field(None, description="Estimated value in cents")


class LeadCreate(LeadBase):
    """Schema for creating a lead."""
    pass


class LeadUpdate(BaseModel):
    """Schema for updating a lead."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    company: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    status: Optional[LeadStatus] = None
    source: Optional[LeadSource] = None
    notes: Optional[str] = None
    estimated_value: Optional[int] = None


class LeadAssign(BaseModel):
    """Schema for assigning a lead."""

    assigned_to_user_id: int = Field(..., description="User ID to assign to")


class Lead(LeadBase):
    """Schema for lead response."""

    id: int
    organization_id: int
    status: LeadStatus
    assigned_to_user_id: Optional[int] = None
    converted_to_user_id: Optional[int] = None
    converted_at: Optional[datetime] = None
    created_by_user_id: int
    last_contacted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LeadListResponse(BaseModel):
    """Schema for paginated lead list response."""

    items: list[Lead]
    total: int
    page: int
    size: int
    pages: int

    class Config:
        from_attributes = True
