"""ISP tenant self-service billing and licence status endpoints."""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.tenant_middleware import get_current_organization_id
from app.models.user import User
from app.models.organization import Organization, OrganizationStatus
from app.models.platform_billing import (
    PlatformInvoice,
    PlatformPayment,
    PlatformSubscriptionTier,
    InvoiceStatus,
)
from app.models.platform_settings import PlatformSettings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/licence-status")
async def get_licence_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get current organization licence/subscription status."""
    # Resolve org from centralized tenant context, fallback to user's org
    org_id = get_current_organization_id() or current_user.organization_id
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not associated with an organization",
        )

    try:
        result = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching organization {org_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch organization data",
        )

    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Get subscription tier info
    tier_info = None
    if org.subscription_tier_id:
        try:
            tier_result = await db.execute(
                select(PlatformSubscriptionTier).where(
                    PlatformSubscriptionTier.id == org.subscription_tier_id
                )
            )
            tier = tier_result.scalar_one_or_none()
            if tier:
                tier_info = {
                    "id": tier.id,
                    "name": tier.name,
                    "description": tier.description,
                    "tier_type": tier.tier_type.value,
                    "base_monthly_fee": float(tier.base_monthly_fee),
                    "max_routers": tier.max_routers,
                    "max_staff_users": tier.max_staff_users,
                    "max_sms_per_month": tier.max_sms_per_month,
                    "features": tier.features or {},
                }
        except Exception as e:
            logger.error(f"Error fetching subscription tier: {e}")

    # Get platform settings for company info
    platform = None
    try:
        platform_result = await db.execute(select(PlatformSettings).limit(1))
        platform = platform_result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching platform settings: {e}")

    return {
        "organization_id": org.id,
        "organization_name": org.name,
        "organization_type": org.organization_type.value if org.organization_type else "hotspot",
        "status": org.status.value,
        "is_trial": org.is_trial,
        "is_subscription_active": org.is_subscription_active,
        "is_in_grace_period": org.is_in_grace_period,
        "is_suspended": org.is_suspended,
        "trial_ends_at": org.trial_ends_at.isoformat() if org.trial_ends_at else None,
        "subscription_ends_at": org.subscription_ends_at.isoformat() if org.subscription_ends_at else None,
        "trial_days_remaining": org.trial_days_remaining,
        "subscription_days_remaining": org.subscription_days_remaining,
        "grace_period_days": org.grace_period_days,
        "grace_period_ends_at": org.grace_period_ends_at.isoformat() if org.grace_period_ends_at else None,
        "licence_bypass": org.licence_bypass,
        "tier": tier_info,
        "usage": {
            "routers": org.max_routers,
            "customers": org.max_customers,
            "staff": org.max_users,
        },
        "platform": {
            "company_name": platform.company_name if platform else "CodeVertex IT Solutions",
            "email": platform.email if platform else "info@codevertexitsolutions.com",
            "phone": platform.phone if platform else None,
            "logo_url": platform.logo_url if platform else "/images/logo/logo.png",
        },
    }


@router.get("/platform-invoices")
async def get_platform_invoices(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    invoice_status: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get platform invoices for the current ISP organization."""
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not associated with an organization",
        )

    query = select(PlatformInvoice).where(
        PlatformInvoice.organization_id == current_user.organization_id
    )

    if invoice_status:
        try:
            status_enum = InvoiceStatus(invoice_status)
            query = query.where(PlatformInvoice.status == status_enum)
        except ValueError:
            pass

    query = query.order_by(PlatformInvoice.created_at.desc())

    # Count total
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    invoices = result.scalars().all()

    return {
        "items": [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "billing_cycle": inv.billing_cycle.value if inv.billing_cycle else None,
                "billing_period_start": inv.billing_period_start.isoformat() if inv.billing_period_start else None,
                "billing_period_end": inv.billing_period_end.isoformat() if inv.billing_period_end else None,
                "base_fee": float(inv.base_fee),
                "earnings_fee": float(inv.earnings_fee),
                "customer_fee": float(inv.customer_fee),
                "additional_fees": float(inv.additional_fees),
                "discount": float(inv.discount),
                "tax": float(inv.tax),
                "total_amount": float(inv.total_amount),
                "status": inv.status.value,
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
                "pdf_url": inv.pdf_url,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in invoices
        ],
        "total": total,
        "page": page,
        "pages": (total + size - 1) // size if total > 0 else 0,
    }
