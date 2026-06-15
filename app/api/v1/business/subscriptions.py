"""Subscriptions API endpoints."""

from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func, select

from app.api.deps import (
    get_current_user,
    require_technician_or_admin,
    PaginationParams,
    enforce_plan_limit,
)
from app.api.deps_org import get_org_id_for_query
from app.core.database import get_db
from app.models.user import User
from app.models.subscription import Subscription as SubscriptionModel, SubscriptionStatus, SubscriptionType


async def _count_subscriptions(db: AsyncSession, organization_id: Optional[int]) -> int:
    """Count existing subscriber subscriptions — used by the max_customers plan gate."""
    query = select(func.count()).select_from(SubscriptionModel)
    if organization_id is not None:
        query = query.where(SubscriptionModel.organization_id == organization_id)
    result = await db.execute(query)
    return int(result.scalar() or 0)
from app.schemas.subscription import (
    Subscription, SubscriptionCreate, SubscriptionUpdate, SubscriptionList,
    SubscriptionStats, SubscriptionFilter, SubscriptionRenewalRequest,
    SubscriptionSuspendRequest, SubscriptionCancelRequest, SubscriptionUsageUpdate,
    SubscriptionUsageLog, SubscriptionHistory
)
from app.modules.subscriptions import SubscriptionService

router = APIRouter()


@router.get("/", response_model=SubscriptionList)
async def get_subscriptions(
    pagination: PaginationParams = Depends(),
    user_id: Optional[int] = Query(None),
    plan_id: Optional[int] = Query(None),
    router_id: Optional[int] = Query(None),
    status: Optional[SubscriptionStatus] = Query(None),
    subscription_type: Optional[SubscriptionType] = Query(None),
    search: Optional[str] = Query(None),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionList:
    """Get all subscriptions with pagination and filters."""
    service = SubscriptionService(db)
    result = await service.get_all(
        pagination=pagination,
        user_id=user_id,
        plan_id=plan_id,
        router_id=router_id,
        status=status,
        subscription_type=subscription_type,
        search=search,
        organization_id=org_id,
    )
    return SubscriptionList(**result)


@router.post(
    "/",
    response_model=Subscription,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_plan_limit("max_customers", _count_subscriptions))],
)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Create a new subscription.

    Phase 3: gated by the central subscriptions-api ``max_customers`` plan limit
    via ``enforce_plan_limit`` (fail-open during migration; superuser /
    platform-owner bypass).
    """
    service = SubscriptionService(db)
    try:
        subscription = await service.create_subscription(
            user_id=subscription_data.user_id,
            plan_id=subscription_data.plan_id,
            router_id=subscription_data.router_id,
            subscription_type=subscription_data.subscription_type,
            username=subscription_data.username,
            password=subscription_data.password,
            start_date=subscription_data.start_date,
            end_date=subscription_data.end_date,
            is_auto_renewal=subscription_data.is_auto_renewal,
            created_by=current_user.id,
            notes=subscription_data.notes,
        )
        return subscription
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{subscription_id}", response_model=Subscription)
async def get_subscription(
    subscription_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Get subscription by ID."""
    service = SubscriptionService(db)
    subscription = await service.get_by_id(subscription_id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    return subscription


@router.patch("/{subscription_id}", response_model=Subscription)
async def update_subscription(
    subscription_id: int,
    subscription_data: SubscriptionUpdate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Update subscription."""
    service = SubscriptionService(db)
    subscription = await service.update_subscription(
        subscription_id, 
        subscription_data.dict(exclude_unset=True),
        current_user.id
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    return subscription


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete subscription."""
    service = SubscriptionService(db)
    success = await service.delete_subscription(subscription_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )


@router.patch("/{subscription_id}/activate", response_model=Subscription)
async def activate_subscription(
    subscription_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Activate subscription."""
    service = SubscriptionService(db)
    subscription = await service.activate_subscription(subscription_id, current_user.id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    return subscription


@router.patch("/{subscription_id}/suspend", response_model=Subscription)
async def suspend_subscription(
    subscription_id: int,
    suspend_data: SubscriptionSuspendRequest,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Suspend subscription."""
    service = SubscriptionService(db)
    subscription = await service.suspend_subscription(
        subscription_id, 
        current_user.id, 
        suspend_data.reason
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    return subscription


@router.patch("/{subscription_id}/cancel", response_model=Subscription)
async def cancel_subscription(
    subscription_id: int,
    cancel_data: SubscriptionCancelRequest,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Cancel subscription."""
    service = SubscriptionService(db)
    subscription = await service.cancel_subscription(
        subscription_id, 
        current_user.id, 
        cancel_data.reason
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    return subscription


@router.post("/{subscription_id}/renew", response_model=Subscription)
async def renew_subscription(
    subscription_id: int,
    renewal_data: SubscriptionRenewalRequest,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Renew subscription."""
    service = SubscriptionService(db)
    subscription = await service.renew_subscription(
        subscription_id, 
        renewal_data.new_end_date,
        current_user.id
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    return subscription


@router.get("/user/{user_id}", response_model=List[Subscription])
async def get_user_subscriptions(
    user_id: int,
    active_only: bool = Query(False),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Subscription]:
    """Get subscriptions for a specific user."""
    # Users can only view their own subscriptions unless they're admin/technician
    if current_user.role not in ["admin", "technician"] and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's subscriptions"
        )
    
    service = SubscriptionService(db)
    subscriptions = await service.get_user_subscriptions(user_id, active_only)
    return subscriptions


@router.get("/{subscription_id}/stats", response_model=SubscriptionStats)
async def get_subscription_stats(
    subscription_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStats:
    """Get subscription statistics."""
    service = SubscriptionService(db)
    stats = await service.get_subscription_stats(subscription_id)
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    return SubscriptionStats(**stats)


@router.get("/{subscription_id}/usage", response_model=List[SubscriptionUsageLog])
async def get_subscription_usage(
    subscription_id: int,
    limit: int = Query(100, ge=1, le=1000),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SubscriptionUsageLog]:
    """Get subscription usage logs."""
    service = SubscriptionService(db)
    usage_logs = await service.get_usage_logs(subscription_id, limit)
    return usage_logs


@router.post("/{subscription_id}/usage", response_model=Dict[str, str])
async def update_subscription_usage(
    subscription_id: int,
    usage_data: SubscriptionUsageUpdate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Update subscription usage."""
    service = SubscriptionService(db)
    success = await service.update_usage(
        subscription_id=subscription_id,
        bytes_uploaded=usage_data.bytes_uploaded,
        bytes_downloaded=usage_data.bytes_downloaded,
        session_duration=usage_data.session_duration,
        ip_address=usage_data.ip_address,
        mac_address=usage_data.mac_address,
    )
    
    if success:
        return {"message": "Usage updated successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update usage"
        )


@router.get("/{subscription_id}/history", response_model=List[SubscriptionHistory])
async def get_subscription_history(
    subscription_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SubscriptionHistory]:
    """Get subscription history."""
    service = SubscriptionService(db)
    history = await service.get_subscription_history(subscription_id)
    return history


@router.get("/expired/", response_model=List[Subscription])
async def get_expired_subscriptions(
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Subscription]:
    """Get expired subscriptions."""
    service = SubscriptionService(db)
    subscriptions = await service.get_expired_subscriptions()
    return subscriptions


@router.get("/expiring/", response_model=List[Subscription])
async def get_expiring_subscriptions(
    days: int = Query(7, ge=1, le=30),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Subscription]:
    """Get subscriptions expiring within specified days."""
    service = SubscriptionService(db)
    subscriptions = await service.get_expiring_subscriptions(days)
    return subscriptions