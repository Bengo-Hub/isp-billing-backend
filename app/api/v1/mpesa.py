"""MPESA API endpoints for payment processing.

This module provides REST API endpoints for MPESA payment operations
following the official Safaricom Daraja API documentation.

Reference: https://developer.safaricom.co.ke/Documentation
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.mpesa_service import MpesaService
from app.core.exceptions import ValidationError, ExternalServiceError, BillingError
from app.schemas.mpesa import (
    MpesaPaymentRequest,
    MpesaPaymentResponse,
    MpesaStatusResponse,
    MpesaCallbackResponse,
    MpesaReversalRequest,
    MpesaReversalResponse,
    MpesaStatisticsResponse
)

router = APIRouter()


@router.post("/initiate-payment", response_model=MpesaPaymentResponse)
async def initiate_payment(
    payment_request: MpesaPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> MpesaPaymentResponse:
    """Initiate MPESA STK Push payment.
    
    This endpoint initiates a payment request that will trigger
    an STK Push on the user's phone for payment confirmation.
    
    Reference: https://developer.safaricom.co.ke/Documentation
    """
    try:
        mpesa_service = MpesaService(db)
        
        result = await mpesa_service.initiate_payment(
            user=current_user,
            amount=payment_request.amount,
            account_reference=payment_request.account_reference,
            description=payment_request.description
        )
        
        return MpesaPaymentResponse(**result)
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ExternalServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MPESA service error: {str(e)}"
        )
    except BillingError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Billing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )


@router.get("/payment-status/{checkout_request_id}", response_model=MpesaStatusResponse)
async def get_payment_status(
    checkout_request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> MpesaStatusResponse:
    """Get payment status using checkout request ID.
    
    This endpoint queries the status of a payment using the
    checkout request ID returned from the initiate payment call.
    
    Reference: https://developer.safaricom.co.ke/Documentation
    """
    try:
        mpesa_service = MpesaService(db)
        
        result = await mpesa_service.query_payment_status(checkout_request_id)
        
        return MpesaStatusResponse(**result)
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ExternalServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MPESA service error: {str(e)}"
        )
    except BillingError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Billing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )


@router.post("/callback", response_model=MpesaCallbackResponse)
async def process_callback(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> MpesaCallbackResponse:
    """Process MPESA callback with signature verification.
    
    This endpoint receives callbacks from MPESA for payment status updates.
    The signature is verified using the official MPESA public key.
    
    Reference: https://developer.safaricom.co.ke/Documentation
    """
    try:
        # Get callback data from request body
        callback_data = await request.json()
        
        mpesa_service = MpesaService(db)
        
        result = await mpesa_service.process_callback(callback_data)
        
        return MpesaCallbackResponse(**result)
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ExternalServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MPESA service error: {str(e)}"
        )
    except BillingError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Billing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )


@router.get("/transaction-status/{transaction_id}", response_model=Dict[str, Any])
async def get_transaction_status(
    transaction_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Get transaction status from MPESA.
    
    This endpoint queries the status of a specific transaction
    using the MPESA Transaction Status Query API.
    
    Reference: https://developer.safaricom.co.ke/Documentation
    """
    try:
        mpesa_service = MpesaService(db)
        
        result = await mpesa_service.get_transaction_status(transaction_id)
        
        return result
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ExternalServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MPESA service error: {str(e)}"
        )
    except BillingError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Billing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )


@router.post("/reverse-payment", response_model=MpesaReversalResponse)
async def reverse_payment(
    reversal_request: MpesaReversalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> MpesaReversalResponse:
    """Reverse a completed payment.
    
    This endpoint initiates a payment reversal using the MPESA
    Reversal API for completed transactions.
    
    Reference: https://developer.safaricom.co.ke/Documentation
    """
    try:
        mpesa_service = MpesaService(db)
        
        result = await mpesa_service.reverse_payment(
            payment_id=reversal_request.payment_id,
            reason=reversal_request.reason
        )
        
        return MpesaReversalResponse(**result)
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ExternalServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MPESA service error: {str(e)}"
        )
    except BillingError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Billing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )


@router.get("/statistics", response_model=MpesaStatisticsResponse)
async def get_payment_statistics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> MpesaStatisticsResponse:
    """Get MPESA payment statistics.
    
    This endpoint provides comprehensive statistics about
    MPESA payments processed through the system.
    """
    try:
        mpesa_service = MpesaService(db)
        
        result = await mpesa_service.get_payment_statistics()
        
        return MpesaStatisticsResponse(**result)
        
    except BillingError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Billing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )
