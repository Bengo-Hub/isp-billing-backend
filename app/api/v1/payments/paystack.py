"""
Paystack Payment API Endpoints.

Complete payment flow endpoints including:
- Payment initiation (get checkout URL)
- Payment verification (callback handling)
- Webhook processing
- Bank/provider lists

These endpoints are used by the frontend for the complete Paystack payment workflow.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, status
from pydantic import BaseModel, Field
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

class PaymentInitiationRequest(BaseModel):
    """Request schema for payment initiation."""
    invoice_id: int = Field(..., description="Invoice ID to pay")
    callback_url: str = Field(..., description="URL to redirect after payment")
    email: Optional[str] = Field(None, description="Customer email")
    phone: Optional[str] = Field(None, description="Customer phone number")


class PaymentInitiationResponse(BaseModel):
    """Response schema for payment initiation."""
    success: bool
    checkout_url: Optional[str] = None
    reference: Optional[str] = None
    access_code: Optional[str] = None
    error: Optional[str] = None


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

@router.post("/initiate", response_model=PaymentInitiationResponse)
async def initiate_payment(
    request_data: PaymentInitiationRequest,
    request: Request,
):
    """
    Initialize a Paystack payment for an invoice.

    This endpoint creates a payment transaction and returns a Paystack
    checkout URL where the customer can complete the payment.

    The callback_url is where the customer will be redirected after
    completing (or abandoning) the payment on Paystack.
    """
    from app.api.deps import get_db_session
    from app.modules.billing import BillingService

    try:
        async with get_db_session() as db:
            billing_service = BillingService(db)

            result = await billing_service.initiate_paystack_payment(
                invoice_id=request_data.invoice_id,
                callback_url=request_data.callback_url,
                user_email=request_data.email,
                user_phone=request_data.phone,
            )

            return PaymentInitiationResponse(**result)

    except Exception as e:
        logger.error(f"Payment initiation error: {e}")
        return PaymentInitiationResponse(
            success=False,
            error=str(e),
        )

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

    This also processes the payment if successful (updates invoice,
    activates subscription, syncs to router).
    """
    from app.api.deps import get_db_session
    from app.modules.billing import BillingService

    try:
        async with get_db_session() as db:
            billing_service = BillingService(db)
            result = await billing_service.verify_paystack_payment(reference)

            return PaymentVerificationResponse(
                success=result.get("success", False),
                status=result.get("status", "pending"),
                message=result.get("message", ""),
                data=result.get("data"),
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
    from app.modules.billing import BillingService

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
            # Find platform-level Paystack gateway (organization_id IS NULL)
            result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
                    PaymentGatewayConfig.organization_id.is_(None),
                    PaymentGatewayConfig.is_active == True,
                ).limit(1)
            )
            gateway_config = result.scalar_one_or_none()

            if not gateway_config:
                logger.warning("No active platform Paystack gateway for webhook")
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

            # Process the webhook event using BillingService
            billing_service = BillingService(db)
            webhook_result = await billing_service.handle_paystack_webhook(event, data)

            return WebhookResponse(
                success=webhook_result.get("success", False),
                message=webhook_result.get("message", f"Webhook processed: {event}"),
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
            # Use platform-level gateway (organization_id IS NULL)
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
                    detail="Platform Paystack gateway not configured",
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
