"""MPESA Service for ISP Billing System.

This service provides a high-level interface for MPESA operations,
integrating with the billing system and providing comprehensive
error handling and logging.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.integrations.mpesa import MpesaAPI
from app.core.logging import get_logger
from app.core.exceptions import ExternalServiceError, ValidationError, BillingError
from app.models.billing import Payment, PaymentStatus, PaymentMethod
from app.models.user import User

logger = get_logger(__name__)


class MpesaService:
    """High-level MPESA service for billing operations."""

    def __init__(self, db: AsyncSession, environment: str = "sandbox"):
        """Initialize MPESA service with database session."""
        self.db = db
        self.logger = get_logger(__name__)
        self.mpesa_api = MpesaAPI(environment=environment)
        self.environment = environment

    async def initiate_payment(self, user: User, amount: int, 
                             account_reference: str, description: str) -> Dict[str, Any]:
        """Initiate STK Push payment for a user."""
        try:
            # Validate user
            if not user or not user.phone_number:
                raise ValidationError("User phone number is required for MPESA payment")
            
            # Validate amount
            if amount <= 0:
                raise ValidationError("Payment amount must be positive")
            
            # Format account reference
            if not account_reference:
                account_reference = f"ISP{user.id:06d}"
            
            # Format description
            if not description:
                description = "ISP Billing Payment"
            
            # Initiate STK Push
            result = await self.mpesa_api.stk_push(
                phone_number=user.phone_number,
                amount=amount,
                account_reference=account_reference,
                transaction_desc=description
            )
            
            if not result.get("success"):
                raise ExternalServiceError(f"STK Push failed: {result.get('error', 'Unknown error')}")
            
            # Create payment record
            payment = Payment(
                user_id=user.id,
                amount=amount,
                currency="KES",
                payment_method=PaymentMethod.MPESA,
                status=PaymentStatus.PENDING,
                external_reference=result["data"].get("CheckoutRequestID"),
                description=description,
                metadata={
                    "mpesa_response": result["data"],
                    "phone_number": result["phone_number"],
                    "account_reference": account_reference
                }
            )
            
            self.db.add(payment)
            await self.db.commit()
            await self.db.refresh(payment)
            
            self.logger.info(f"MPESA payment initiated for user {user.id}: {amount} KES")
            
            return {
                "success": True,
                "payment_id": payment.id,
                "checkout_request_id": result["data"].get("CheckoutRequestID"),
                "amount": amount,
                "phone_number": result["phone_number"],
                "message": "Payment request sent to your phone"
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error initiating MPESA payment: {e}")
            raise BillingError(f"Failed to initiate payment: {e}")

    async def query_payment_status(self, checkout_request_id: str) -> Dict[str, Any]:
        """Query payment status using checkout request ID."""
        try:
            if not checkout_request_id:
                raise ValidationError("Checkout request ID is required")
            
            # Query MPESA API
            result = await self.mpesa_api.query_stk_push_status(checkout_request_id)
            
            if not result.get("success"):
                raise ExternalServiceError(f"Status query failed: {result.get('error', 'Unknown error')}")
            
            # Find payment record
            payment_result = await self.db.execute(
                select(Payment).where(Payment.external_reference == checkout_request_id)
            )
            payment = payment_result.scalar_one_or_none()
            
            if not payment:
                raise ValidationError("Payment record not found")
            
            # Update payment status based on MPESA response
            mpesa_data = result["data"]
            if mpesa_data.get("ResultCode") == 0:
                payment.status = PaymentStatus.COMPLETED
                payment.metadata = {
                    **payment.metadata,
                    "mpesa_status_response": mpesa_data,
                    "completed_at": datetime.utcnow().isoformat()
                }
            else:
                payment.status = PaymentStatus.FAILED
                payment.metadata = {
                    **payment.metadata,
                    "mpesa_status_response": mpesa_data,
                    "failed_at": datetime.utcnow().isoformat(),
                    "failure_reason": mpesa_data.get("ResultDesc", "Unknown error")
                }
            
            await self.db.commit()
            
            self.logger.info(f"Payment status updated for {checkout_request_id}: {payment.status}")
            
            return {
                "success": True,
                "payment_id": payment.id,
                "status": payment.status.value,
                "amount": payment.amount,
                "mpesa_response": mpesa_data
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error querying payment status: {e}")
            raise BillingError(f"Failed to query payment status: {e}")

    async def process_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process MPESA callback with signature verification."""
        try:
            # Verify callback signature
            if not self.mpesa_api.verify_callback_signature(callback_data):
                self.logger.warning("Invalid MPESA callback signature")
                raise ValidationError("Invalid callback signature")
            
            # Parse callback data
            parsed_data = self.mpesa_api.parse_stk_callback(callback_data)
            
            if not parsed_data.get("success"):
                raise ValidationError(f"Failed to parse callback: {parsed_data.get('error')}")
            
            checkout_request_id = parsed_data.get("checkout_request_id")
            result_code = parsed_data.get("result_code")
            
            if not checkout_request_id:
                raise ValidationError("Missing checkout request ID in callback")
            
            # Find payment record
            payment_result = await self.db.execute(
                select(Payment).where(Payment.external_reference == checkout_request_id)
            )
            payment = payment_result.scalar_one_or_none()
            
            if not payment:
                self.logger.warning(f"Payment not found for checkout request: {checkout_request_id}")
                return {"success": False, "error": "Payment not found"}
            
            # Update payment status
            if result_code == 0:
                payment.status = PaymentStatus.COMPLETED
                payment.metadata = {
                    **payment.metadata,
                    "mpesa_callback": parsed_data,
                    "completed_at": datetime.utcnow().isoformat()
                }
                self.logger.info(f"Payment completed: {payment.id}")
            else:
                payment.status = PaymentStatus.FAILED
                payment.metadata = {
                    **payment.metadata,
                    "mpesa_callback": parsed_data,
                    "failed_at": datetime.utcnow().isoformat(),
                    "failure_reason": parsed_data.get("result_desc", "Unknown error")
                }
                self.logger.warning(f"Payment failed: {payment.id} - {parsed_data.get('result_desc')}")
            
            await self.db.commit()
            
            return {
                "success": True,
                "payment_id": payment.id,
                "status": payment.status.value,
                "result_code": result_code
            }
            
        except ValidationError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error processing MPESA callback: {e}")
            raise BillingError(f"Failed to process callback: {e}")

    async def get_transaction_status(self, transaction_id: str) -> Dict[str, Any]:
        """Get transaction status from MPESA."""
        try:
            if not transaction_id:
                raise ValidationError("Transaction ID is required")
            
            result = await self.mpesa_api.get_transaction_status(transaction_id)
            
            if not result.get("success"):
                raise ExternalServiceError(f"Transaction status query failed: {result.get('error')}")
            
            self.logger.info(f"Transaction status retrieved for {transaction_id}")
            
            return {
                "success": True,
                "transaction_id": transaction_id,
                "status_data": result["data"]
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error getting transaction status: {e}")
            raise BillingError(f"Failed to get transaction status: {e}")

    async def reverse_payment(self, payment_id: int, reason: str = "Payment reversal") -> Dict[str, Any]:
        """Reverse a completed payment."""
        try:
            # Get payment record
            payment_result = await self.db.execute(
                select(Payment).where(Payment.id == payment_id)
            )
            payment = payment_result.scalar_one_or_none()
            
            if not payment:
                raise ValidationError("Payment not found")
            
            if payment.status != PaymentStatus.COMPLETED:
                raise ValidationError("Only completed payments can be reversed")
            
            if not payment.external_reference:
                raise ValidationError("Payment has no external reference for reversal")
            
            # Get user for phone number
            user_result = await self.db.execute(
                select(User).where(User.id == payment.user_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user or not user.phone_number:
                raise ValidationError("User phone number not found for reversal")
            
            # Initiate reversal
            result = await self.mpesa_api.reverse_transaction(
                transaction_id=payment.external_reference,
                amount=payment.amount,
                receiver_party=user.phone_number,
                remarks=reason
            )
            
            if not result.get("success"):
                raise ExternalServiceError(f"Reversal failed: {result.get('error')}")
            
            # Update payment status
            payment.status = PaymentStatus.REVERSED
            payment.metadata = {
                **payment.metadata,
                "reversal_request": result["data"],
                "reversed_at": datetime.utcnow().isoformat(),
                "reversal_reason": reason
            }
            
            await self.db.commit()
            
            self.logger.info(f"Payment reversal initiated for {payment_id}")
            
            return {
                "success": True,
                "payment_id": payment_id,
                "reversal_data": result["data"]
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error reversing payment: {e}")
            raise BillingError(f"Failed to reverse payment: {e}")

    async def get_payment_statistics(self) -> Dict[str, Any]:
        """Get MPESA payment statistics."""
        try:
            # Get total MPESA payments
            total_result = await self.db.execute(
                select(Payment).where(Payment.payment_method == PaymentMethod.MPESA)
            )
            total_payments = total_result.scalars().all()
            
            # Calculate statistics
            total_count = len(total_payments)
            completed_count = len([p for p in total_payments if p.status == PaymentStatus.COMPLETED])
            pending_count = len([p for p in total_payments if p.status == PaymentStatus.PENDING])
            failed_count = len([p for p in total_payments if p.status == PaymentStatus.FAILED])
            
            total_amount = sum(p.amount for p in total_payments if p.status == PaymentStatus.COMPLETED)
            success_rate = (completed_count / total_count * 100) if total_count > 0 else 0
            
            return {
                "success": True,
                "statistics": {
                    "total_payments": total_count,
                    "completed_payments": completed_count,
                    "pending_payments": pending_count,
                    "failed_payments": failed_count,
                    "total_amount": total_amount,
                    "success_rate": round(success_rate, 2)
                }
            }
            
        except Exception as e:
            self.logger.error(f"Unexpected error getting payment statistics: {e}")
            raise BillingError(f"Failed to get payment statistics: {e}")
