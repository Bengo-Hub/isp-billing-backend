"""MPESA Service for ISP Billing System.

This service provides a high-level interface for MPESA operations,
integrating with the billing system and providing comprehensive
error handling and logging.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ExternalServiceError, ValidationError, BillingError
from app.models.billing import Payment, PaymentStatus, PaymentMethod
from app.models.user import User

# NOTE (Phase 3 cleanup): the local M-PESA gateway integration package was removed —
# customer/tenant payment initiation + confirmation are centralized on treasury-api.
# MpesaService is retained importable for back-compat; its gateway-backed methods now
# report that direct M-PESA processing is unavailable (use treasury-api instead).

logger = get_logger(__name__)


class MPesaValidationError(Exception):
    """Retained local validation error (gateway package removed)."""


_GATEWAY_RETIRED_MSG = (
    "Direct M-PESA gateway processing has been retired in isp-billing — "
    "payment initiation/confirmation is now handled by treasury-api."
)


def _get_mpesa_config() -> Dict[str, Any]:
    """Build M-PESA gateway configuration from settings."""
    return {
        "credentials": {
            "consumer_key": getattr(settings, "mpesa_consumer_key", ""),
            "consumer_secret": getattr(settings, "mpesa_consumer_secret", ""),
            "passkey": getattr(settings, "mpesa_passkey", ""),
            "shortcode": getattr(settings, "mpesa_shortcode", ""),
            "environment": getattr(settings, "mpesa_environment", "sandbox"),
            "initiator_name": getattr(settings, "mpesa_initiator_name", ""),
            "security_credential": getattr(settings, "mpesa_security_credential", ""),
        },
        "callback_url": getattr(settings, "mpesa_callback_url", ""),
        "timeout_url": getattr(settings, "mpesa_timeout_url", ""),
        "result_url": getattr(settings, "mpesa_result_url", ""),
    }


def _is_mpesa_configured() -> bool:
    """Check if M-PESA is properly configured."""
    required_fields = ["mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_passkey", "mpesa_shortcode"]
    placeholder_patterns = ["your-mpesa-", "placeholder", "change-me", "example"]

    for field in required_fields:
        value = getattr(settings, field, "")
        if not value:
            return False
        if any(pattern in value.lower() for pattern in placeholder_patterns):
            return False
    return True


class MpesaService:
    """High-level MPESA service for billing operations."""

    def __init__(self, db: AsyncSession, environment: str = "sandbox"):
        """Initialize MPESA service with database session."""
        self.db = db
        self.logger = get_logger(__name__)
        self.environment = environment
        # Gateway integration retired (Phase 2/3) — treasury-api owns M-PESA
        # initiation/confirmation. The service stays importable for back-compat but
        # reports itself unconfigured so all gateway-backed methods short-circuit.
        self._is_configured = False
        self.gateway = None

    @property
    def is_configured(self) -> bool:
        """Check if MPESA service is properly configured."""
        return self._is_configured

    async def initiate_payment(self, user: User, amount: int,
                             account_reference: str, description: str) -> Dict[str, Any]:
        """Initiate STK Push payment for a user."""
        if not self._is_configured:
            self.logger.warning("MPESA service not configured. Payment initiation skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Payment processing unavailable in development mode"
            }

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
                description = "ISP Billing"

            # Get callback URL
            callback_url = getattr(settings, "mpesa_callback_url", "")

            # Initiate STK Push using gateway
            result = await self.gateway.initiate_payment(
                amount=Decimal(str(amount)),
                phone_number=user.phone_number,
                reference=account_reference,
                description=description,
                callback_url=callback_url,
            )

            if not result.success:
                raise ExternalServiceError(f"STK Push failed: {result.message}")

            # Create payment record
            payment = Payment(
                user_id=user.id,
                amount=amount,
                currency="KES",
                payment_method=PaymentMethod.MPESA,
                status=PaymentStatus.PENDING,
                external_reference=result.gateway_reference,
                description=description,
                metadata={
                    "merchant_request_id": result.metadata.get("merchant_request_id") if result.metadata else None,
                    "checkout_request_id": result.gateway_reference,
                    "phone_number": user.phone_number,
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
                "checkout_request_id": result.gateway_reference,
                "amount": amount,
                "phone_number": user.phone_number,
                "message": result.message or "Payment request sent to your phone"
            }

        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except MPesaValidationError as e:
            raise ValidationError(str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error initiating MPESA payment: {e}")
            raise BillingError(f"Failed to initiate payment: {e}")

    async def query_payment_status(self, checkout_request_id: str) -> Dict[str, Any]:
        """Query payment status using checkout request ID."""
        if not self._is_configured:
            self.logger.warning("MPESA service not configured. Status query skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Payment verification unavailable in development mode"
            }

        try:
            if not checkout_request_id:
                raise ValidationError("Checkout request ID is required")

            # Query MPESA API using gateway
            result = await self.gateway.verify_payment(checkout_request_id)

            # Find payment record
            payment_result = await self.db.execute(
                select(Payment).where(Payment.external_reference == checkout_request_id)
            )
            payment = payment_result.scalar_one_or_none()

            if not payment:
                raise ValidationError("Payment record not found")

            # Update payment status based on MPESA response.
            # (Gateway status enum retired with the integration package; aliased to the
            # local enum so this now-unreachable branch references a defined name.)
            from app.models.billing import PaymentStatus as GatewayPaymentStatus

            if result.status == GatewayPaymentStatus.COMPLETED:
                payment.status = PaymentStatus.COMPLETED
                payment.metadata = {
                    **(payment.metadata or {}),
                    "mpesa_status_response": result.raw_response,
                    "completed_at": datetime.utcnow().isoformat()
                }
            elif result.status == GatewayPaymentStatus.CANCELLED:
                payment.status = PaymentStatus.FAILED
                payment.metadata = {
                    **(payment.metadata or {}),
                    "mpesa_status_response": result.raw_response,
                    "failed_at": datetime.utcnow().isoformat(),
                    "failure_reason": "Payment cancelled by user"
                }
            elif result.status == GatewayPaymentStatus.FAILED:
                payment.status = PaymentStatus.FAILED
                payment.metadata = {
                    **(payment.metadata or {}),
                    "mpesa_status_response": result.raw_response,
                    "failed_at": datetime.utcnow().isoformat(),
                    "failure_reason": result.message or "Payment failed"
                }

            await self.db.commit()

            self.logger.info(f"Payment status updated for {checkout_request_id}: {payment.status}")

            return {
                "success": True,
                "payment_id": payment.id,
                "status": payment.status.value,
                "amount": payment.amount,
                "mpesa_response": result.raw_response
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
        if not self._is_configured:
            self.logger.warning("MPESA service not configured. Callback processing skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Callback processing unavailable in development mode"
            }

        try:
            # Verify callback signature (optional, depends on key availability)
            if not self.gateway.verify_callback_signature(callback_data):
                self.logger.warning("Invalid MPESA callback signature - continuing with basic validation")

            # Parse callback data
            parsed_data = self.gateway.parse_stk_callback(callback_data)

            if not parsed_data:
                raise ValidationError("Failed to parse callback data")

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
            if result_code == 0 or result_code == "0":
                payment.status = PaymentStatus.COMPLETED
                payment.metadata = {
                    **(payment.metadata or {}),
                    "mpesa_callback": parsed_data,
                    "completed_at": datetime.utcnow().isoformat()
                }
                self.logger.info(f"Payment completed: {payment.id}")
            else:
                payment.status = PaymentStatus.FAILED
                payment.metadata = {
                    **(payment.metadata or {}),
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
        if not self._is_configured:
            self.logger.warning("MPESA service not configured. Transaction status query skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Transaction status unavailable in development mode"
            }

        try:
            if not transaction_id:
                raise ValidationError("Transaction ID is required")

            result = await self.gateway.transaction_status(transaction_id)

            if "error" in result:
                raise ExternalServiceError(f"Transaction status query failed: {result.get('error')}")

            self.logger.info(f"Transaction status retrieved for {transaction_id}")

            return {
                "success": True,
                "transaction_id": transaction_id,
                "status_data": result
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
        if not self._is_configured:
            self.logger.warning("MPESA service not configured. Payment reversal skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Payment reversal unavailable in development mode"
            }

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

            # Initiate reversal using gateway
            result = await self.gateway.refund_payment(
                transaction_reference=payment.external_reference,
                amount=Decimal(str(payment.amount)),
                reason=reason
            )

            if not result.success:
                raise ExternalServiceError(f"Reversal failed: {result.message}")

            # Update payment status
            payment.status = PaymentStatus.REVERSED
            payment.metadata = {
                **(payment.metadata or {}),
                "reversal_request": result.raw_response,
                "reversed_at": datetime.utcnow().isoformat(),
                "reversal_reason": reason
            }

            await self.db.commit()

            self.logger.info(f"Payment reversal initiated for {payment_id}")

            return {
                "success": True,
                "payment_id": payment_id,
                "reversal_data": result.raw_response
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
