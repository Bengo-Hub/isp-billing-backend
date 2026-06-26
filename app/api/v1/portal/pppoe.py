"""
PPPoE Customer Portal API.

Endpoints for PPPoE customers to:
- Login to their dashboard
- View usage statistics
- View payment history
- Renew subscriptions
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.api.deps_tenant import get_organization_by_slug
from app.core.security import create_access_token, verify_password
from app.models.organization import Organization
from app.models.user import User, UserRole, UserStatus
from app.models.plan import ServicePlan, PlanType
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionUsageLog, SubscriptionType
from app.models.billing import Payment, PaymentStatus

router = APIRouter(prefix="/pppoe", tags=["Portal - PPPoE"])


# =========================================================================
# Schemas
# =========================================================================

class CustomerLoginRequest(BaseModel):
    """Schema for customer login."""

    username: str
    password: str


class CustomerLoginResponse(BaseModel):
    """Schema for login response."""

    access_token: str
    token_type: str = "bearer"
    customer: dict


class RenewalRequest(BaseModel):
    """Schema for subscription renewal request."""

    plan_id: int
    phone_number: str


class RenewalResponse(BaseModel):
    """Schema for renewal response."""

    success: bool
    reference: str
    message: str
    checkout_url: Optional[str] = None


class PlanResponse(BaseModel):
    """Schema for plan details."""

    id: int
    name: str
    description: Optional[str]
    price: float
    currency: str
    validity_days: int
    download_speed: int
    upload_speed: int
    data_limit: Optional[int]
    is_current: bool = False


# =========================================================================
# Endpoints
# =========================================================================

@router.post("/{org_slug}/login", response_model=CustomerLoginResponse)
async def customer_login(
    org_slug: str,
    data: CustomerLoginRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Customer login for PPPoE dashboard.

    Returns access token for authenticated requests.
    """
    # Find user by username within organization
    result = await db.execute(
        select(User).where(
            User.organization_id == organization.id,
            User.role == UserRole.CUSTOMER,
            User.username == data.username,
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active"
        )

    # Create access token
    token = create_access_token(
        data={
            "sub": str(user.id),
            "organization_id": organization.id,
            "role": user.role.value,
        }
    )

    # Update last login
    user.last_login = datetime.utcnow()
    await db.flush()

    # Sync user to MikroTik router if they have an active subscription
    from app.models.router import Router
    from app.modules.routers.mikrotik import get_mikrotik_client
    import logging

    logger = logging.getLogger(__name__)

    # Get user's active subscription
    sub_result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(
            Subscription.user_id == user.id,
            Subscription.organization_id == organization.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    active_subscription = sub_result.scalar_one_or_none()

    if active_subscription and active_subscription.plan:
        # Get organization's router
        router_result = await db.execute(
            select(Router).where(
                Router.organization_id == organization.id,
                Router.is_active == True,
            ).limit(1)
        )
        router = router_result.scalar_one_or_none()

        if router:
            try:
                # Connect to router
                client = get_mikrotik_client()
                connection = await client.connect(
                    ip_address=router.ip_address,
                    username=router.username,
                    password=router.password,
                    port=router.port,
                )

                plan = active_subscription.plan

                # Use plan's time_limit (in seconds) if set, otherwise unlimited
                time_limit_seconds = plan.time_limit if plan.time_limit > 0 else None

                # Calculate data limit in bytes (plan.data_limit is in MB)
                data_limit_bytes = None
                if plan.data_limit > 0 and not plan.is_unlimited_data:
                    data_limit_bytes = plan.data_limit * 1024 * 1024  # MB to bytes

                # Create or update PPPoE user with bandwidth and data/time limits
                # Note: MikroTik uses kbps for bandwidth, plan stores in Mbps
                await client.create_pppoe_user(
                    connection=connection,
                    username=user.username,
                    password=data.password,  # Use the password they just logged in with
                    profile="default",
                    service="pppoe",
                    **{
                        "limit-bytes-total": data_limit_bytes if data_limit_bytes else None,
                        "limit-uptime": f"{time_limit_seconds}s" if time_limit_seconds else None,
                        "comment": f"PPPoE user - {plan.name} subscription",
                    }
                )

                await client.disconnect(router.ip_address, router.port)

                logger.info(
                    f"Synced PPPoE user {user.username} to router {router.name} "
                    f"on login with plan {plan.name}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to sync PPPoE user {user.username} to router {router.name}: {e}. "
                    f"User may need to reconnect manually."
                )
                # Don't fail login if router sync fails
        else:
            logger.warning(
                f"No active router found for organization {organization.id}. "
                f"PPPoE user {user.username} not synced to router."
            )
    else:
        logger.info(
            f"User {user.username} has no active subscription. "
            f"Not syncing to router."
        )

    await db.commit()

    return CustomerLoginResponse(
        access_token=token,
        customer={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name,
        },
    )


@router.get("/{org_slug}/dashboard")
async def get_dashboard(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
):
    """
    Get customer dashboard data.

    Includes current plan, subscription status, and quick stats.
    """
    # Get user
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == organization.id,
            User.role == UserRole.CUSTOMER,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    # Get active subscription
    sub_result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(
            Subscription.user_id == user.id,
            Subscription.organization_id == organization.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = sub_result.scalar_one_or_none()

    # Get usage stats for current month
    first_day = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    usage_result = await db.execute(
        select(
            func.sum(SubscriptionUsageLog.bytes_in).label("total_bytes_in"),
            func.sum(SubscriptionUsageLog.bytes_out).label("total_bytes_out"),
            func.sum(SubscriptionUsageLog.duration).label("total_duration"),
        )
        .where(
            SubscriptionUsageLog.subscription_id == subscription.id if subscription else 0,
            SubscriptionUsageLog.created_at >= first_day,
        )
    )
    usage = usage_result.first()

    total_bytes_in = usage.total_bytes_in or 0
    total_bytes_out = usage.total_bytes_out or 0
    total_duration = usage.total_duration or 0

    # Convert bytes to GB
    data_used_gb = (total_bytes_in + total_bytes_out) / (1024 * 1024 * 1024)

    # Get payment history
    payment_result = await db.execute(
        select(Payment)
        .where(
            Payment.user_id == user.id,
            Payment.organization_id == organization.id,
        )
        .order_by(Payment.created_at.desc())
        .limit(5)
    )
    payments = payment_result.scalars().all()

    return {
        "customer": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "full_name": user.full_name,
        },
        "subscription": {
            "id": subscription.id if subscription else None,
            "status": subscription.status.value if subscription else None,
            "plan_name": subscription.plan.name if subscription and subscription.plan else None,
            "start_date": subscription.start_date.isoformat() if subscription and subscription.start_date else None,
            "end_date": subscription.end_date.isoformat() if subscription and subscription.end_date else None,
            "download_speed": subscription.plan.download_speed if subscription and subscription.plan else 0,
            "upload_speed": subscription.plan.upload_speed if subscription and subscription.plan else 0,
            "data_limit": subscription.plan.data_limit if subscription and subscription.plan else 0,
        } if subscription else None,
        "usage": {
            "data_used_gb": round(data_used_gb, 2),
            "total_duration_hours": round(total_duration / 3600, 2),
        },
        "payments": [
            {
                "id": p.id,
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status.value,
                "payment_method": p.payment_method,
                "created_at": p.created_at.isoformat(),
            }
            for p in payments
        ],
    }


@router.get("/{org_slug}/usage")
async def get_usage_history(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
    days: int = Query(30, description="Number of days to fetch", ge=1, le=90),
):
    """
    Get usage history for the last N days.

    Returns daily usage breakdown.
    """
    # Get active subscription
    sub_result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.organization_id == organization.id,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = sub_result.scalar_one_or_none()

    if not subscription:
        return {"usage": []}

    # Get usage logs
    start_date = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(SubscriptionUsageLog)
        .where(
            SubscriptionUsageLog.subscription_id == subscription.id,
            SubscriptionUsageLog.created_at >= start_date,
        )
        .order_by(SubscriptionUsageLog.created_at.desc())
    )
    logs = result.scalars().all()

    return {
        "usage": [
            {
                "date": log.created_at.date().isoformat(),
                "bytes_in": log.bytes_in,
                "bytes_out": log.bytes_out,
                "duration": log.duration,
                "data_used_mb": (log.bytes_in + log.bytes_out) / (1024 * 1024),
            }
            for log in logs
        ]
    }


@router.get("/{org_slug}/payments")
async def get_payment_history(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
    limit: int = Query(10, description="Number of payments to fetch", ge=1, le=100),
):
    """
    Get payment history.

    Returns list of recent payments.
    """
    result = await db.execute(
        select(Payment)
        .where(
            Payment.user_id == user_id,
            Payment.organization_id == organization.id,
        )
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    payments = result.scalars().all()

    return {
        "payments": [
            {
                "id": p.id,
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status.value,
                "payment_method": p.payment_method,
                "payment_reference": p.payment_reference,
                "description": p.description,
                "created_at": p.created_at.isoformat(),
            }
            for p in payments
        ]
    }


@router.get("/{org_slug}/plans", response_model=List[PlanResponse])
async def get_available_plans(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
):
    """
    Get available PPPoE plans for renewal.

    Includes indication of which plan is current.
    """
    # Get user's current subscription
    sub_result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(
            Subscription.user_id == user_id,
            Subscription.organization_id == organization.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    current_subscription = sub_result.scalar_one_or_none()
    current_plan_id = current_subscription.plan_id if current_subscription else None

    # Get all available PPPoE plans
    plans_result = await db.execute(
        select(ServicePlan)
        .where(
            ServicePlan.organization_id == organization.id,
            ServicePlan.plan_type == PlanType.PPPOE,
            ServicePlan.is_active == True,
        )
        .order_by(ServicePlan.price.asc())
    )
    plans = plans_result.scalars().all()

    return [
        PlanResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            price=float(p.price),
            currency=p.currency,
            validity_days=p.validity_days,
            download_speed=p.download_speed,
            upload_speed=p.upload_speed,
            data_limit=p.data_limit if p.data_limit > 0 else None,
            is_current=p.id == current_plan_id,
        )
        for p in plans
    ]


@router.post("/{org_slug}/renew", response_model=RenewalResponse)
async def renew_subscription(
    org_slug: str,
    data: RenewalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
):
    """
    Renew subscription with a new or same plan via treasury-api.

    Payments are centralized on treasury-api (the single payment path): a payment
    intent is created under the ISP tenant's UUID and the customer is handed the
    shared treasury pay page. Confirmation runs via the verify endpoint below
    (treasury get_status) — there is no local-gateway fallback.
    """
    import uuid
    from app.models.billing import PaymentMethod
    from app.services.treasury_topup import create_topup_intent

    # Get plan
    plan_result = await db.execute(
        select(ServicePlan).where(
            ServicePlan.id == data.plan_id,
            ServicePlan.organization_id == organization.id,
        )
    )
    plan = plan_result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Package not found"
        )

    tenant_uuid = str(organization.uuid) if getattr(organization, "uuid", None) else None
    if not tenant_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to resolve billing tenant for this organization",
        )

    reference = f"PPP-{organization.slug[:6].upper()}-{uuid.uuid4().hex[:8].upper()}"

    # Create a pending Payment record (treasury intent id stored on transaction_id).
    payment = Payment(
        organization_id=organization.id,
        user_id=user_id,
        payment_number=reference,
        amount=plan.price,
        currency=plan.currency,
        reference_number=reference,
        payment_method=PaymentMethod.OTHER,
        status=PaymentStatus.PENDING,
        notes=f"PPPoE Subscription Renewal - {plan.name}",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    # Build the isp-billing callback the customer returns to after paying.
    origin = request.headers.get("origin", "")
    redirect_url = (
        f"{origin}/payment/callback?payment_type=pppoe_renewal&org={org_slug}&reference={reference}"
        if origin else ""
    )

    intent = await create_topup_intent(
        tenant_uuid=tenant_uuid,
        amount=str(plan.price),
        currency=plan.currency,
        reference=reference,
        reference_type="pppoe_renewal",
        description=f"Renewal - {plan.name}",
        redirect_url=redirect_url,
        customer_phone=data.phone_number or None,
        metadata={
            "organization_id": organization.id,
            "user_id": user_id,
            "plan_id": plan.id,
            "payment_id": payment.id,
            "type": "renewal",
        },
        button_text="Renew",
    )

    if intent is None:
        payment.status = PaymentStatus.FAILED
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service is temporarily unavailable. Please try again.",
        )

    payment.transaction_id = intent.intent_id
    await db.commit()

    return RenewalResponse(
        success=True,
        reference=reference,
        message="Choose a payment method to complete your renewal.",
        checkout_url=intent.checkout_url,
    )


# =========================================================================
# Payment Verification (Paystack direct API verification - no webhook needed)
# =========================================================================


@router.get("/{org_slug}/payment/verify")
async def verify_pppoe_payment(
    org_slug: str,
    reference: str = Query(..., description="Payment reference"),
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Verify a PPPoE renewal payment via treasury-api.

    Called by the frontend callback page after the customer returns from the
    shared treasury pay page. Polls the treasury payment intent (get_status) for
    the payment's stored intent id; on success renews the subscription. Treasury
    owns confirmation (NATS consumer primary, this poll is the fallback).
    """
    import logging
    from app.services.treasury_topup import get_intent_status, SUCCESS_STATUSES, FAILURE_STATUSES

    logger = logging.getLogger(__name__)

    # 1. Find the payment record
    result = await db.execute(
        select(Payment).where(
            Payment.reference_number == reference,
            Payment.organization_id == organization.id,
        )
    )
    payment = result.scalar_one_or_none()

    if not payment:
        return {
            "success": False,
            "status": "not_found",
            "message": "Payment not found for this reference",
        }

    # 2. Already completed - return success
    if payment.status == PaymentStatus.COMPLETED:
        return {
            "success": True,
            "status": "success",
            "message": "Payment already processed",
            "data": {
                "reference": reference,
                "amount": float(payment.amount),
                "currency": payment.currency,
            },
        }

    # 3. Verify with treasury-api
    if not payment.transaction_id:
        return {
            "success": False,
            "status": "error",
            "message": "No treasury payment intent associated with this payment",
        }

    tenant_uuid = str(organization.uuid) if getattr(organization, "uuid", None) else None
    treasury_status = await get_intent_status(
        tenant_uuid=tenant_uuid, intent_id=payment.transaction_id
    ) if tenant_uuid else None

    if treasury_status is None:
        return {
            "success": False,
            "status": "error",
            "message": "Unable to verify payment with treasury. Please try again.",
        }

    if treasury_status in FAILURE_STATUSES:
        payment.status = PaymentStatus.FAILED
        await db.commit()
        return {
            "success": False,
            "status": treasury_status,
            "message": f"Payment {treasury_status}",
        }

    if treasury_status not in SUCCESS_STATUSES:
        return {
            "success": False,
            "status": "pending",
            "message": "Payment is still pending",
        }

    # 4. Payment confirmed — renew the subscription
    payment.status = PaymentStatus.COMPLETED
    payment.payment_date = datetime.utcnow()
    await db.flush()

    await _process_pppoe_subscription_renewal(db, payment, organization, logger)
    await db.commit()

    return {
        "success": True,
        "status": "success",
        "message": "Payment verified and subscription renewed",
        "data": {
            "reference": reference,
            "amount": float(payment.amount),
            "currency": payment.currency,
        },
    }


async def _process_pppoe_subscription_renewal(
    db: AsyncSession,
    payment: Payment,
    organization: Organization,
    logger,
):
    """
    Process subscription renewal after successful PPPoE payment.

    Shared logic used by both the verify endpoint and the webhook handler.
    """
    # Get user
    user_result = await db.execute(
        select(User).where(User.id == payment.user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user:
        logger.error(f"User not found for payment {payment.id}")
        return

    # Get user's most recent subscription to determine the plan
    sub_result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(
            Subscription.user_id == user.id,
            Subscription.organization_id == organization.id,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    existing_subscription = sub_result.scalar_one_or_none()

    if existing_subscription and existing_subscription.plan:
        plan = existing_subscription.plan
    else:
        logger.error(f"Cannot determine plan for payment {payment.id}")
        return

    # Create new subscription or extend existing one
    if existing_subscription and existing_subscription.status == SubscriptionStatus.ACTIVE:
        # Extend existing subscription
        if existing_subscription.end_date:
            new_end_date = existing_subscription.end_date + timedelta(days=plan.validity_days)
        else:
            new_end_date = datetime.utcnow() + timedelta(days=plan.validity_days)

        existing_subscription.end_date = new_end_date
        existing_subscription.updated_at = datetime.utcnow()

        logger.info(f"Extended subscription {existing_subscription.id} until {new_end_date}")
        subscription = existing_subscription
    else:
        # Create new subscription
        start_date = datetime.utcnow()
        end_date = start_date + timedelta(days=plan.validity_days)

        subscription = Subscription(
            organization_id=organization.id,
            user_id=user.id,
            plan_id=plan.id,
            subscription_type=SubscriptionType.PPPOE,
            start_date=start_date,
            end_date=end_date,
            status=SubscriptionStatus.ACTIVE,
            username=user.username,
            password=user.hashed_password,
        )
        db.add(subscription)
        await db.flush()

        logger.info(f"Created new subscription {subscription.id} for user {user.username}")

    # Sync user to MikroTik router
    from app.models.router import Router
    from app.modules.routers.mikrotik import get_mikrotik_client

    router_result = await db.execute(
        select(Router).where(
            Router.organization_id == organization.id,
            Router.is_active == True,
        ).limit(1)
    )
    router_obj = router_result.scalar_one_or_none()

    if router_obj:
        try:
            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router_obj.ip_address,
                username=router_obj.username,
                password=router_obj.password,
                port=router_obj.port,
            )

            time_limit_seconds = plan.time_limit if plan.time_limit > 0 else None
            data_limit_bytes = None
            if plan.data_limit > 0 and not plan.is_unlimited_data:
                data_limit_bytes = plan.data_limit * 1024 * 1024

            await client.create_pppoe_user(
                connection=connection,
                username=user.username,
                password=user.hashed_password,
                profile="default",
                service="pppoe",
                **{
                    "limit-bytes-total": data_limit_bytes if data_limit_bytes else None,
                    "limit-uptime": f"{time_limit_seconds}s" if time_limit_seconds else None,
                    "comment": f"PPPoE subscription - {plan.name} - Valid until {subscription.end_date.date()}",
                }
            )

            await client.disconnect(router_obj.ip_address, router_obj.port)

            logger.info(
                f"Synced PPPoE user {user.username} to router {router_obj.name} "
                f"for subscription {subscription.id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to sync PPPoE user {user.username} to router {router_obj.name}: {e}. "
                f"User may need to reconnect manually."
            )
    else:
        logger.warning(
            f"No active router found for organization {organization.id}. "
            f"PPPoE user {user.username} not synced to router."
        )

    # Phase C2 (ADDITIVE): emit isp.* domain events for the PPPoE renewal in the
    # SAME transaction (caller commits). notifications-api consumes these to send
    # the customer-facing payment-confirmation / credentials message. Fully
    # guarded — eventing must never break provisioning; inert until NATS is set.
    try:
        from app.events.outbox import record_event
        from app.events import EVT_PAYMENT_RECEIVED, EVT_SUBSCRIPTION_RENEWED

        tenant_uuid = str(organization.uuid) if organization.uuid else None
        customer_name = (
            " ".join(filter(None, [getattr(user, "first_name", None), getattr(user, "last_name", None)])).strip()
            or user.email
            or user.username
        )
        customer_phone = getattr(user, "phone", None)
        expiry_at = subscription.end_date.isoformat() if subscription.end_date else None

        record_event(
            db,
            event_type=EVT_PAYMENT_RECEIVED,
            tenant_id=tenant_uuid,
            aggregate_id=str(payment.id),
            payload={
                "payment_id": payment.id,
                "organization_id": organization.id,
                "organization_slug": organization.slug,
                "user_id": user.id,
                "plan_id": plan.id,
                "plan_name": plan.name,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "payment_method": getattr(payment, "payment_method", None) and str(payment.payment_method),
                "payment_reference": payment.reference_number,
                "phone_number": customer_phone,
                "email": user.email,
            },
        )
        record_event(
            db,
            # Renewal (not a new subscriber) — notifications-api renders the
            # ispbilling/subscription_renewal template (a "renewed" confirmation,
            # not a fresh-credentials message; the PPPoE secret is unchanged).
            event_type=EVT_SUBSCRIPTION_RENEWED,
            tenant_id=tenant_uuid,
            aggregate_id=str(subscription.id),
            payload={
                # tenant (ISP org) + identifiers
                "tenant_id": tenant_uuid,
                "organization_id": organization.id,
                "organization_slug": organization.slug,
                "subscription_id": subscription.id,
                "user_id": user.id,
                "payment_id": payment.id,
                # customer
                "customer_name": customer_name,
                "phone": customer_phone,
                "email": user.email,
                # package + lifecycle
                "plan_id": plan.id,
                "package_name": plan.name,
                "package_type": "pppoe",
                "subscriber_type": "pppoe",
                "expiry_at": expiry_at,
                "amount": str(payment.amount),
                "currency": payment.currency,
            },
        )
    except Exception as evt_exc:  # eventing must never break provisioning
        logger.warning(
            "failed to record outbox events for pppoe payment %s: %s", payment.id, evt_exc
        )


@router.post("/{org_slug}/webhooks/payment")
async def pppoe_payment_webhook(
    org_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    PPPoE payment callback webhook.

    Receives payment notifications from payment gateways and creates/renews subscriptions.
    """
    import json
    import logging

    logger = logging.getLogger(__name__)

    try:
        body = await request.body()
        payload = json.loads(body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Extract reference from different gateway formats
    reference = None
    payment_status_str = None

    # M-PESA callback format
    if "Body" in payload and "stkCallback" in payload.get("Body", {}):
        stk = payload["Body"]["stkCallback"]
        reference = stk.get("CheckoutRequestID")
        result_code = stk.get("ResultCode")
        payment_status_str = "completed" if result_code == 0 else "failed"

    # Paystack callback format
    elif "event" in payload and "data" in payload:
        event_type = payload.get("event", "")
        data = payload.get("data", {})
        reference = data.get("reference")

        if event_type == "charge.success":
            payment_status_str = "completed"
        elif event_type in ["charge.failed", "transfer.failed"]:
            payment_status_str = "failed"

    # Generic format (direct reference)
    elif "reference" in payload:
        reference = payload.get("reference")
        payment_status_str = payload.get("status", "completed")

    if not reference:
        logger.warning(f"No reference found in webhook payload: {payload}")
        return {"status": "received", "message": "No reference found"}

    # Find the payment record
    result = await db.execute(
        select(Payment)
        .where(
            Payment.payment_reference == reference,
            Payment.organization_id == organization.id,
        )
    )
    payment = result.scalar_one_or_none()

    if not payment:
        logger.warning(f"Payment not found for reference: {reference}")
        return {"status": "received", "message": "Payment not found"}

    # Update payment status
    if payment_status_str == "completed":
        payment.status = PaymentStatus.COMPLETED
        payment.paid_at = datetime.utcnow()
    elif payment_status_str == "failed":
        payment.status = PaymentStatus.FAILED
    else:
        payment.status = PaymentStatus.PENDING

    await db.flush()

    if payment_status_str == "completed":
        await _process_pppoe_subscription_renewal(db, payment, organization, logger)

    await db.commit()

    logger.info(f"Processed PPPoE payment webhook for reference {reference}: status={payment_status_str}")
    return {"status": "received", "payment_status": payment_status_str}
