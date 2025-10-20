"""Pydantic schemas for MPESA operations.

This module defines the data models for MPESA API requests and responses
following the official Safaricom Daraja API documentation.

Reference: https://developer.safaricom.co.ke/Documentation
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, validator


class MpesaPaymentRequest(BaseModel):
    """Request schema for initiating MPESA payment."""
    amount: int = Field(..., gt=0, le=150000, description="Payment amount in KES (1-150,000)")
    account_reference: Optional[str] = Field(None, max_length=12, description="Account reference (max 12 characters)")
    description: Optional[str] = Field(None, max_length=13, description="Transaction description (max 13 characters)")

    @validator('amount')
    def validate_amount(cls, v):
        if v < 1:
            raise ValueError('Amount must be at least 1 KES')
        if v > 150000:
            raise ValueError('Amount cannot exceed 150,000 KES')
        return v

    @validator('account_reference')
    def validate_account_reference(cls, v):
        if v and len(v) > 12:
            raise ValueError('Account reference must be 12 characters or less')
        return v

    @validator('description')
    def validate_description(cls, v):
        if v and len(v) > 13:
            raise ValueError('Description must be 13 characters or less')
        return v


class MpesaPaymentResponse(BaseModel):
    """Response schema for MPESA payment initiation."""
    success: bool = Field(..., description="Whether the payment initiation was successful")
    payment_id: int = Field(..., description="Internal payment ID")
    checkout_request_id: str = Field(..., description="MPESA checkout request ID")
    amount: int = Field(..., description="Payment amount in KES")
    phone_number: str = Field(..., description="Phone number used for payment")
    message: str = Field(..., description="User-friendly message")


class MpesaStatusResponse(BaseModel):
    """Response schema for payment status query."""
    success: bool = Field(..., description="Whether the status query was successful")
    payment_id: int = Field(..., description="Internal payment ID")
    status: str = Field(..., description="Payment status")
    amount: int = Field(..., description="Payment amount in KES")
    mpesa_response: Dict[str, Any] = Field(..., description="Raw MPESA API response")


class MpesaCallbackResponse(BaseModel):
    """Response schema for MPESA callback processing."""
    success: bool = Field(..., description="Whether the callback was processed successfully")
    payment_id: int = Field(..., description="Internal payment ID")
    status: str = Field(..., description="Updated payment status")
    result_code: int = Field(..., description="MPESA result code")


class MpesaReversalRequest(BaseModel):
    """Request schema for payment reversal."""
    payment_id: int = Field(..., gt=0, description="Payment ID to reverse")
    reason: Optional[str] = Field("Payment reversal", max_length=100, description="Reason for reversal")


class MpesaReversalResponse(BaseModel):
    """Response schema for payment reversal."""
    success: bool = Field(..., description="Whether the reversal was initiated successfully")
    payment_id: int = Field(..., description="Payment ID that was reversed")
    reversal_data: Dict[str, Any] = Field(..., description="MPESA reversal response data")


class MpesaStatisticsResponse(BaseModel):
    """Response schema for payment statistics."""
    success: bool = Field(..., description="Whether the statistics were retrieved successfully")
    statistics: Dict[str, Any] = Field(..., description="Payment statistics data")


class MpesaTransactionStatusRequest(BaseModel):
    """Request schema for transaction status query."""
    transaction_id: str = Field(..., min_length=1, description="MPESA transaction ID")


class MpesaTransactionStatusResponse(BaseModel):
    """Response schema for transaction status query."""
    success: bool = Field(..., description="Whether the query was successful")
    transaction_id: str = Field(..., description="Transaction ID queried")
    status_data: Dict[str, Any] = Field(..., description="Transaction status data from MPESA")


class MpesaErrorResponse(BaseModel):
    """Error response schema for MPESA operations."""
    success: bool = Field(False, description="Always false for error responses")
    error: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Error code if available")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


class MpesaCallbackData(BaseModel):
    """Schema for MPESA callback data structure."""
    Body: Dict[str, Any] = Field(..., description="Callback body data")
    stkCallback: Dict[str, Any] = Field(..., description="STK callback data")
    signature: str = Field(..., description="Callback signature for verification")

    class Config:
        extra = "allow"  # Allow additional fields from MPESA


class MpesaStkCallbackData(BaseModel):
    """Schema for STK callback data structure."""
    MerchantRequestID: str = Field(..., description="Merchant request ID")
    CheckoutRequestID: str = Field(..., description="Checkout request ID")
    ResultCode: int = Field(..., description="Result code from MPESA")
    ResultDesc: str = Field(..., description="Result description")
    CallbackMetadata: Optional[Dict[str, Any]] = Field(None, description="Callback metadata")

    class Config:
        extra = "allow"  # Allow additional fields from MPESA


class MpesaCallbackMetadata(BaseModel):
    """Schema for callback metadata."""
    Item: Optional[list] = Field(None, description="List of metadata items")

    class Config:
        extra = "allow"  # Allow additional fields from MPESA


class MpesaMetadataItem(BaseModel):
    """Schema for individual metadata item."""
    Name: str = Field(..., description="Metadata item name")
    Value: str = Field(..., description="Metadata item value")

    class Config:
        extra = "allow"  # Allow additional fields from MPESA
