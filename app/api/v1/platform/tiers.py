"""
Platform Owner API - Subscription Tiers.

Endpoints for managing platform subscription tiers.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import require_platform_owner
from app.models.user import User
from app.models.platform_billing import TierType
from app.modules.platform_billing.service import PlatformBillingService
from app.modules.platform_billing.schemas import (
    SubscriptionTierCreate,
    SubscriptionTierUpdate,
    SubscriptionTierResponse,
)

router = APIRouter(prefix="/tiers", tags=["Platform - Subscription Tiers"])


@router.get("/public", response_model=List[SubscriptionTierResponse])
async def list_public_subscription_tiers(
    db: AsyncSession = Depends(get_db),
    tier_type: Optional[TierType] = None,
):
    """
    List active subscription tiers for public display (e.g. landing page pricing).

    No authentication required.
    """
    billing_service = PlatformBillingService(db)
    tiers = await billing_service.get_subscription_tiers(
        tier_type=tier_type,
        active_only=True,
    )
    return [SubscriptionTierResponse.model_validate(tier) for tier in tiers]


@router.get("/", response_model=List[SubscriptionTierResponse])
async def list_subscription_tiers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
    tier_type: Optional[TierType] = None,
    include_inactive: bool = False,
):
    """
    List all subscription tiers.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    tiers = await billing_service.get_subscription_tiers(
        tier_type=tier_type,
        active_only=not include_inactive,
    )
    return [SubscriptionTierResponse.model_validate(tier) for tier in tiers]


@router.post("/", response_model=SubscriptionTierResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription_tier(
    data: SubscriptionTierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Create a new subscription tier.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    tier = await billing_service.create_subscription_tier(data.model_dump())
    return SubscriptionTierResponse.model_validate(tier)


@router.get("/{tier_id}", response_model=SubscriptionTierResponse)
async def get_subscription_tier(
    tier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get a subscription tier by ID.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    tier = await billing_service.get_subscription_tier(tier_id)

    if not tier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription tier not found"
        )

    return SubscriptionTierResponse.model_validate(tier)


@router.patch("/{tier_id}", response_model=SubscriptionTierResponse)
async def update_subscription_tier(
    tier_id: int,
    data: SubscriptionTierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Update a subscription tier.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    tier = await billing_service.update_subscription_tier(
        tier_id,
        data.model_dump(exclude_unset=True),
    )

    if not tier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription tier not found"
        )

    return SubscriptionTierResponse.model_validate(tier)


@router.delete("/{tier_id}")
async def delete_subscription_tier(
    tier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Deactivate a subscription tier.

    Note: Tiers are never deleted, only deactivated.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    tier = await billing_service.update_subscription_tier(
        tier_id,
        {"is_active": False},
    )

    if not tier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription tier not found"
        )

    return {"message": "Subscription tier deactivated"}


@router.post("/seed-defaults")
async def seed_default_tiers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Seed default subscription tiers.

    Creates Hotspot and PPPoE tiers if they don't exist.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)

    # Check if tiers exist
    existing_hotspot = await billing_service.get_default_tier(TierType.HOTSPOT)
    existing_pppoe = await billing_service.get_default_tier(TierType.PPPOE)

    created = []

    if not existing_hotspot:
        # Create Hotspot tier
        hotspot_tier = await billing_service.create_subscription_tier({
            "name": "Hotspot Basic",
            "description": "Base entry package for Hotspot ISPs. KES 500/month + 2% on earnings above 10k.",
            "tier_type": TierType.HOTSPOT,
            "base_monthly_fee": 500,
            "earnings_threshold": 10000,
            "earnings_percentage": 2.0,
            "max_routers": 5,
            "max_staff_users": 3,
            "max_sms_per_month": 100,
            "trial_days": 14,
            "is_active": True,
            "is_default": True,
            "display_order": 1,
            "features": {
                "custom_domain": False,
                "white_label": False,
                "api_access": True,
                "priority_support": False,
                "advanced_analytics": False,
                "voucher_system": True,
                "sms_notifications": True,
            },
        })
        created.append(hotspot_tier.name)

    if not existing_pppoe:
        # Create PPPoE tiers (following CodeVertex model)
        pppoe_basic = await billing_service.create_subscription_tier({
            "name": "PPPoE Starter",
            "description": "Starter package for PPPoE ISPs with up to 50 customers.",
            "tier_type": TierType.PPPOE,
            "base_monthly_fee": 1000,
            "min_customers": 0,
            "max_customers": 50,
            "max_routers": 3,
            "max_staff_users": 2,
            "max_sms_per_month": 50,
            "trial_days": 14,
            "is_active": True,
            "is_default": True,
            "display_order": 1,
            "features": {
                "custom_domain": False,
                "white_label": False,
                "api_access": False,
                "priority_support": False,
                "advanced_analytics": False,
                "multi_router": True,
                "sms_notifications": True,
            },
        })
        created.append(pppoe_basic.name)

        # Create PPPoE Growth tier
        pppoe_growth = await billing_service.create_subscription_tier({
            "name": "PPPoE Growth",
            "description": "Growth package for PPPoE ISPs with 51-200 customers.",
            "tier_type": TierType.PPPOE,
            "base_monthly_fee": 2500,
            "min_customers": 51,
            "max_customers": 200,
            "max_routers": 10,
            "max_staff_users": 5,
            "max_sms_per_month": 200,
            "trial_days": 14,
            "is_active": True,
            "is_default": False,
            "display_order": 2,
            "badge_text": "Popular",
            "badge_color": "#ec4899",
            "features": {
                "custom_domain": True,
                "white_label": False,
                "api_access": True,
                "priority_support": False,
                "advanced_analytics": True,
                "multi_router": True,
                "sms_notifications": True,
            },
        })
        created.append(pppoe_growth.name)

        # Create PPPoE Enterprise tier
        pppoe_enterprise = await billing_service.create_subscription_tier({
            "name": "PPPoE Enterprise",
            "description": "Enterprise package for large PPPoE ISPs with 200+ customers.",
            "tier_type": TierType.PPPOE,
            "base_monthly_fee": 5000,
            "min_customers": 201,
            "max_customers": None,  # Unlimited
            "per_customer_fee": 15,  # KES 15 per customer above 200
            "max_routers": 50,
            "max_staff_users": 20,
            "max_sms_per_month": 1000,
            "trial_days": 14,
            "is_active": True,
            "is_default": False,
            "display_order": 3,
            "features": {
                "custom_domain": True,
                "white_label": True,
                "api_access": True,
                "priority_support": True,
                "advanced_analytics": True,
                "multi_router": True,
                "sms_notifications": True,
            },
        })
        created.append(pppoe_enterprise.name)

    return {
        "message": f"Created {len(created)} subscription tiers",
        "created": created,
    }
