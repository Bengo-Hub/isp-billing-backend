"""
Paystack Payment API Endpoints.

Public endpoints for payment verification and webhooks.
These endpoints are used by the frontend callback page and Paystack webhooks.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
from app.integrations.payment_gateways import PaymentGatewayFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/paystack", tags=["Payments - Paystack"])


# =============================================================================
# Schemas
# =============================================================================

class PaymentVerificationResponse(BaseModel):
    """Response schema for payment verification."""
    success: bool
    status: str  # success, failed, pending, abandoned
    message: str
    data: Optional[dict] = None


class WebhookResponse(BaseModel):
    """Response schema for webhook processing."""
    success: bool
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/verify/{reference}", response_model=PaymentVerificationResponse)
async def verify_payment(
    reference: str,
    request: Request,
):
    """
    Verify a Paystack payment by reference.

    This endpoint is called by the frontend callback page after
    a customer completes payment on Paystack.

    The reference is passed as a query parameter by Paystack
    when redirecting back to the callback URL.
    """
    from app.api.deps import get_db_session

    try:
        # Get database session
        async with get_db_session() as db:
            # Find an active Paystack gateway
            # In production, you'd extract org_id from the reference or metadata
            result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
                    PaymentGatewayConfig.is_active == True,
                ).limit(1)
            )
            gateway_config = result.scalar_one_or_none()

            if not gateway_config:
                logger.error("No active Paystack gateway found")
                return PaymentVerificationResponse(
                    success=False,
                    status="failed",
                    message="Payment gateway not configured",
                )

            # Create gateway instance and verify payment
            gateway = PaymentGatewayFactory.create(gateway_config)
            verification = await gateway.verify_payment(reference)

            if verification.success:
                return PaymentVerificationResponse(
                    success=True,
                    status="success",
                    message="Payment verified successfully",
                    data={
                        "reference": reference,
                        "amount": float(verification.amount) if verification.amount else None,
                        "currency": verification.currency,
                        "paid_at": verification.paid_at.isoformat() if verification.paid_at else None,
                        "channel": verification.raw_response.get("data", {}).get("channel") if verification.raw_response else None,
                        "customer_email": verification.raw_response.get("data", {}).get("customer", {}).get("email") if verification.raw_response else None,
                    },
                )
            else:
                # Determine status from verification result
                status_str = "failed"
                if verification.status:
                    status_str = verification.status.value.lower()

                return PaymentVerificationResponse(
                    success=False,
                    status=status_str,
                    message=verification.message or "Payment verification failed",
                    data={
                        "reference": reference,
                    },
                )

    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return PaymentVerificationResponse(
            success=False,
            status="pending",
            message="Unable to verify payment. Please check your email for confirmation.",
            data={"reference": reference},
        )


@router.post("/webhook", response_model=WebhookResponse)
async def paystack_webhook(
    request: Request,
    x_paystack_signature: Optional[str] = Header(None, alias="x-paystack-signature"),
):
    """
    Handle Paystack webhook events.

    Paystack sends webhook notifications for various events:
    - charge.success: Payment was successful
    - charge.failed: Payment failed
    - transfer.success: Transfer completed
    - transfer.failed: Transfer failed
    - subscription.create: New subscription created
    - invoice.payment_failed: Subscription payment failed

    All webhooks are signed with HMAC SHA512 using your secret key.
    """
    from app.api.deps import get_db_session

    try:
        # Get raw body for signature verification
        body = await request.body()
        body_str = body.decode("utf-8")

        # Parse JSON payload
        import json
        payload = json.loads(body_str)

        event = payload.get("event", "")
        data = payload.get("data", {})

        logger.info(f"Paystack webhook received: {event}")

        async with get_db_session() as db:
            # Find active Paystack gateway
            result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
                    PaymentGatewayConfig.is_active == True,
                ).limit(1)
            )
            gateway_config = result.scalar_one_or_none()

            if not gateway_config:
                logger.warning("No active Paystack gateway for webhook")
                return WebhookResponse(success=True, message="No gateway configured")

            # Verify webhook signature if provided
            gateway = PaymentGatewayFactory.create(gateway_config)

            if x_paystack_signature:
                if not gateway.verify_webhook_signature(body_str, x_paystack_signature):
                    logger.warning("Invalid webhook signature")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid signature",
                    )

            # Process the webhook event
            if event == "charge.success":
                # Payment successful - update payment record
                reference = data.get("reference")
                amount = data.get("amount", 0) / 100  # Convert from kobo

                logger.info(f"Payment successful: {reference}, amount: {amount}")

                # TODO: Update your payment/invoice record here
                # Example:
                # await update_payment_status(db, reference, "completed", amount)

            elif event == "charge.failed":
                reference = data.get("reference")
                logger.info(f"Payment failed: {reference}")

                # TODO: Update payment record to failed
                # await update_payment_status(db, reference, "failed")

            elif event == "transfer.success":
                reference = data.get("reference")
                logger.info(f"Transfer successful: {reference}")

            elif event == "transfer.failed":
                reference = data.get("reference")
                reason = data.get("reason", "Unknown")
                logger.info(f"Transfer failed: {reference}, reason: {reason}")

            elif event == "subscription.create":
                subscription_code = data.get("subscription_code")
                logger.info(f"Subscription created: {subscription_code}")

            elif event == "invoice.payment_failed":
                subscription_code = data.get("subscription", {}).get("subscription_code")
                logger.info(f"Subscription payment failed: {subscription_code}")

            else:
                logger.info(f"Unhandled webhook event: {event}")

            return WebhookResponse(
                success=True,
                message=f"Webhook processed: {event}",
            )

    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        # Return 200 to prevent Paystack from retrying
        return WebhookResponse(
            success=False,
            message=str(e),
        )


@router.get("/banks/{country}")
async def list_banks(country: str = "kenya"):
    """
    Get list of banks for the specified country.

    Used for setting up transfer recipients.

    Supported countries: nigeria, ghana, south-africa, kenya
    """
    from app.api.deps import get_db_session

    try:
        async with get_db_session() as db:
            result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
                    PaymentGatewayConfig.is_active == True,
                ).limit(1)
            )
            gateway_config = result.scalar_one_or_none()

            if not gateway_config:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Paystack gateway not configured",
                )

            gateway = PaymentGatewayFactory.create(gateway_config)
            banks = await gateway.list_banks(country)

            if banks.get("status"):
                return banks
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=banks.get("message", "Failed to fetch banks"),
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List banks error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/resolve-account")
async def resolve_account(
    account_number: str,
    bank_code: str,
):
    """
    Resolve a bank account to get the account holder name.

    This verifies that the account exists and returns the account holder's name.
    Used for validating payout configuration before saving.

    Args:
        account_number: The bank account number
        bank_code: The bank code (from list_banks endpoint)

    Returns:
        Account details including account_name
    """
    from app.api.deps import get_db_session

    try:
        async with get_db_session() as db:
            # Get platform-level Paystack gateway (organization_id = NULL)
            result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
                    PaymentGatewayConfig.organization_id.is_(None),
                    PaymentGatewayConfig.is_active == True,
                ).limit(1)
            )
            gateway_config = result.scalar_one_or_none()

            if not gateway_config:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Paystack gateway not configured",
                )

            gateway = PaymentGatewayFactory.create(gateway_config)
            account_info = await gateway.resolve_account_number(account_number, bank_code)

            if account_info.get("status"):
                return {
                    "status": True,
                    "data": account_info.get("data", {}),
                    "message": account_info.get("message", "Account resolved successfully"),
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=account_info.get("message", "Failed to resolve account"),
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resolve account error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
