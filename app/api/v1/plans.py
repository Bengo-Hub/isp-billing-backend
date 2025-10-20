"""Plans API endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.plan import PlanType, PlanStatus
from app.schemas.plan import (
    ServicePlan, ServicePlanCreate, ServicePlanUpdate, ServicePlanList,
    ServicePlanStats, PlanFeature, PlanFeatureCreate, PlanFeatureUpdate,
    PlanPricing, PlanPricingCreate, PlanPricingUpdate
)
from app.services.plan_service import PlanService

router = APIRouter()


@router.get("/", response_model=ServicePlanList)
async def get_plans(
    pagination: PaginationParams = Depends(),
    plan_type: Optional[PlanType] = Query(None),
    status: Optional[PlanStatus] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ServicePlanList:
    """Get all service plans with pagination and filters."""
    service = PlanService(db)
    result = await service.get_all(
        pagination=pagination,
        plan_type=plan_type,
        status=status,
        is_active=is_active,
        search=search,
    )
    return ServicePlanList(**result)


@router.post("/", response_model=ServicePlan, status_code=status.HTTP_201_CREATED)
async def create_plan(
    plan_data: ServicePlanCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> ServicePlan:
    """Create a new service plan."""
    service = PlanService(db)
    try:
        plan = await service.create_plan(
            name=plan_data.name,
            description=plan_data.description,
            plan_type=plan_data.plan_type,
            price=plan_data.price,
            currency=plan_data.currency,
            billing_cycle=plan_data.billing_cycle,
            download_speed=plan_data.download_speed,
            upload_speed=plan_data.upload_speed,
            data_limit=plan_data.data_limit,
            time_limit=plan_data.time_limit,
            validity_days=plan_data.validity_days,
            fup_enabled=plan_data.fup_enabled,
            fup_threshold=plan_data.fup_threshold,
            fup_download_speed=plan_data.fup_download_speed,
            fup_upload_speed=plan_data.fup_upload_speed,
            concurrent_sessions=plan_data.concurrent_sessions,
            auto_renewal=plan_data.auto_renewal,
            is_popular=plan_data.is_popular,
            sort_order=plan_data.sort_order,
            config=plan_data.config,
            notes=plan_data.notes,
        )
        return plan
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{plan_id}", response_model=ServicePlan)
async def get_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ServicePlan:
    """Get plan by ID."""
    service = PlanService(db)
    plan = await service.get_by_id(plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )
    return plan


@router.patch("/{plan_id}", response_model=ServicePlan)
async def update_plan(
    plan_id: int,
    plan_data: ServicePlanUpdate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> ServicePlan:
    """Update plan."""
    service = PlanService(db)
    plan = await service.update_plan(plan_id, plan_data.dict(exclude_unset=True))
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete plan."""
    service = PlanService(db)
    try:
        success = await service.delete_plan(plan_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{plan_id}/activate", response_model=ServicePlan)
async def activate_plan(
    plan_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> ServicePlan:
    """Activate plan."""
    service = PlanService(db)
    plan = await service.activate_plan(plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )
    return plan


@router.patch("/{plan_id}/deactivate", response_model=ServicePlan)
async def deactivate_plan(
    plan_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> ServicePlan:
    """Deactivate plan."""
    service = PlanService(db)
    plan = await service.deactivate_plan(plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )
    return plan


@router.get("/{plan_id}/stats", response_model=ServicePlanStats)
async def get_plan_stats(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ServicePlanStats:
    """Get plan statistics."""
    service = PlanService(db)
    stats = await service.get_plan_stats(plan_id)
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )
    return ServicePlanStats(**stats)


@router.get("/popular/", response_model=List[ServicePlan])
async def get_popular_plans(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ServicePlan]:
    """Get popular service plans."""
    service = PlanService(db)
    plans = await service.get_popular_plans(limit)
    return plans


@router.get("/type/{plan_type}/", response_model=List[ServicePlan])
async def get_plans_by_type(
    plan_type: PlanType,
    limit: Optional[int] = Query(None, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ServicePlan]:
    """Get plans by type."""
    service = PlanService(db)
    plans = await service.get_plans_by_type(plan_type, limit)
    return plans


# Plan Features endpoints
@router.get("/{plan_id}/features", response_model=List[PlanFeature])
async def get_plan_features(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[PlanFeature]:
    """Get plan features."""
    service = PlanService(db)
    features = await service.get_plan_features(plan_id)
    return features


@router.post("/{plan_id}/features", response_model=PlanFeature, status_code=status.HTTP_201_CREATED)
async def add_plan_feature(
    plan_id: int,
    feature_data: PlanFeatureCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> PlanFeature:
    """Add feature to plan."""
    service = PlanService(db)
    feature = await service.add_plan_feature(
        plan_id=plan_id,
        feature_name=feature_data.feature_name,
        feature_value=feature_data.feature_value,
        is_included=feature_data.is_included,
        sort_order=feature_data.sort_order,
    )
    return feature


@router.delete("/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_plan_feature(
    feature_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove feature from plan."""
    service = PlanService(db)
    success = await service.remove_plan_feature(feature_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature not found"
        )


# Plan Pricing endpoints
@router.get("/{plan_id}/pricing", response_model=List[PlanPricing])
async def get_plan_pricing(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[PlanPricing]:
    """Get plan pricing tiers."""
    service = PlanService(db)
    pricing = await service.get_plan_pricing(plan_id)
    return pricing


@router.post("/{plan_id}/pricing", response_model=PlanPricing, status_code=status.HTTP_201_CREATED)
async def add_plan_pricing(
    plan_id: int,
    pricing_data: PlanPricingCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> PlanPricing:
    """Add pricing tier to plan."""
    service = PlanService(db)
    pricing = await service.add_plan_pricing(
        plan_id=plan_id,
        duration_months=pricing_data.duration_months,
        price=pricing_data.price,
        discount_percentage=pricing_data.discount_percentage,
    )
    return pricing