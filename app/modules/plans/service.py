"""Service plan management service."""

from typing import Any, Dict, List, Optional
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import ServicePlan, PlanFeature, PlanPricing, PlanType, PlanStatus, BillingCycle
from app.api.deps import PaginationParams


class PlanService:
    """Service plan management service."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, plan_id: int) -> Optional[ServicePlan]:
        """Get plan by ID."""
        return await self.db.get(ServicePlan, plan_id)

    async def get_all(
        self,
        pagination: PaginationParams,
        plan_type: Optional[PlanType] = None,
        status: Optional[PlanStatus] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Get all service plans with pagination and filters."""
        query = select(ServicePlan)

        # Apply filters
        if plan_type:
            query = query.where(ServicePlan.plan_type == plan_type)
        if status:
            query = query.where(ServicePlan.status == status)
        if is_active is not None:
            # Convert boolean to status enum
            target_status = PlanStatus.ACTIVE if is_active else PlanStatus.INACTIVE
            query = query.where(ServicePlan.status == target_status)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (ServicePlan.name.ilike(search_term))
                | (ServicePlan.description.ilike(search_term))
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get plans with pagination
        query = query.order_by(ServicePlan.sort_order.asc(), ServicePlan.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        plans = result.scalars().all()

        return {
            "plans": plans,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_plan(
        self,
        name: str,
        description: str,
        plan_type: PlanType,
        price: Decimal,
        currency: str,
        billing_cycle: BillingCycle,
        download_speed: int,
        upload_speed: int,
        data_limit: int = -1,
        time_limit: int = -1,
        validity_days: int = 30,
        fup_enabled: bool = False,
        fup_threshold: Optional[int] = None,
        fup_download_speed: Optional[int] = None,
        fup_upload_speed: Optional[int] = None,
        concurrent_sessions: int = 1,
        auto_renewal: bool = False,
        is_popular: bool = False,
        sort_order: int = 0,
        enable_burst: bool = False,
        burst_download: Optional[int] = None,
        burst_upload: Optional[int] = None,
        burst_threshold: Optional[int] = None,
        burst_time: Optional[int] = None,
        enable_schedule: bool = False,
        schedule_start_time: Optional[str] = None,
        schedule_end_time: Optional[str] = None,
        config: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ServicePlan:
        """Create a new service plan."""
        plan = ServicePlan(
            name=name,
            description=description,
            plan_type=plan_type,
            price=price,
            currency=currency,
            billing_cycle=billing_cycle,
            download_speed=download_speed,
            upload_speed=upload_speed,
            data_limit=data_limit,
            time_limit=time_limit,
            validity_days=validity_days,
            fup_enabled=fup_enabled,
            fup_threshold=fup_threshold,
            fup_download_speed=fup_download_speed,
            fup_upload_speed=fup_upload_speed,
            concurrent_sessions=concurrent_sessions,
            auto_renewal=auto_renewal,
            is_popular=is_popular,
            sort_order=sort_order,
            enable_burst=enable_burst,
            burst_download=burst_download,
            burst_upload=burst_upload,
            burst_threshold=burst_threshold,
            burst_time=burst_time,
            enable_schedule=enable_schedule,
            schedule_start_time=schedule_start_time,
            schedule_end_time=schedule_end_time,
            config=config,
            notes=notes,
            status=PlanStatus.ACTIVE,
        )

        self.db.add(plan)
        await self.db.commit()
        await self.db.refresh(plan)

        return plan

    async def update_plan(
        self, 
        plan_id: int, 
        update_data: Dict[str, Any]
    ) -> Optional[ServicePlan]:
        """Update service plan."""
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None

        # Update fields
        for field, value in update_data.items():
            if hasattr(plan, field) and value is not None:
                setattr(plan, field, value)

        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def delete_plan(self, plan_id: int) -> bool:
        """Delete service plan (soft delete by setting status to discontinued)."""
        plan = await self.get_by_id(plan_id)
        if not plan:
            return False

        # Check if plan has active subscriptions
        from app.models.subscription import Subscription
        result = await self.db.execute(
            select(Subscription).where(Subscription.plan_id == plan_id)
        )
        active_subscriptions = result.scalars().all()
        
        if active_subscriptions:
            # Soft delete by setting status to discontinued
            plan.status = PlanStatus.DISCONTINUED
            await self.db.commit()
        else:
            # Hard delete if no subscriptions
            await self.db.delete(plan)
            await self.db.commit()

        return True

    async def activate_plan(self, plan_id: int) -> Optional[ServicePlan]:
        """Activate service plan."""
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None

        plan.status = PlanStatus.ACTIVE
        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def deactivate_plan(self, plan_id: int) -> Optional[ServicePlan]:
        """Deactivate service plan."""
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None

        plan.status = PlanStatus.INACTIVE
        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def get_plan_features(self, plan_id: int) -> List[PlanFeature]:
        """Get plan features."""
        result = await self.db.execute(
            select(PlanFeature).where(PlanFeature.plan_id == plan_id)
        )
        return result.scalars().all()

    async def get_plan_stats(self) -> Dict[str, Any]:
        """Get plan statistics."""
        # Total plans
        result = await self.db.execute(select(func.count(ServicePlan.id)))
        total_plans = result.scalar() or 0
        
        # Active plans
        result = await self.db.execute(
            select(func.count(ServicePlan.id)).where(ServicePlan.is_active == True)
        )
        active_plans = result.scalar() or 0
        
        # Plans by type
        result = await self.db.execute(
            select(ServicePlan.plan_type, func.count(ServicePlan.id))
            .group_by(ServicePlan.plan_type)
        )
        plans_by_type = dict(result.fetchall())
        
        return {
            "total_plans": total_plans,
            "active_plans": active_plans,
            "plans_by_type": plans_by_type
        }

    async def add_plan_feature(
        self,
        plan_id: int,
        feature_name: str,
        feature_value: Optional[str] = None,
        is_included: bool = True,
        sort_order: int = 0,
    ) -> PlanFeature:
        """Add feature to plan."""
        feature = PlanFeature(
            plan_id=plan_id,
            feature_name=feature_name,
            feature_value=feature_value,
            is_included=is_included,
            sort_order=sort_order,
        )

        self.db.add(feature)
        await self.db.commit()
        await self.db.refresh(feature)
        return feature

    async def remove_plan_feature(self, feature_id: int) -> bool:
        """Remove feature from plan."""
        feature = await self.db.get(PlanFeature, feature_id)
        if not feature:
            return False

        await self.db.delete(feature)
        await self.db.commit()
        return True

    async def get_plan_pricing(self, plan_id: int) -> List[PlanPricing]:
        """Get plan pricing tiers."""
        result = await self.db.execute(
            select(PlanPricing).where(PlanPricing.plan_id == plan_id)
        )
        return result.scalars().all()

    async def add_plan_pricing(
        self,
        plan_id: int,
        duration_months: int,
        price: Decimal,
        discount_percentage: Decimal = Decimal('0'),
    ) -> PlanPricing:
        """Add pricing tier to plan."""
        pricing = PlanPricing(
            plan_id=plan_id,
            duration_months=duration_months,
            price=price,
            discount_percentage=discount_percentage,
        )

        self.db.add(pricing)
        await self.db.commit()
        await self.db.refresh(pricing)
        return pricing

    async def get_popular_plans(self, limit: int = 10) -> List[ServicePlan]:
        """Get popular service plans."""
        result = await self.db.execute(
            select(ServicePlan)
            .where(ServicePlan.is_popular == True)
            .where(ServicePlan.status == PlanStatus.ACTIVE)
            .order_by(ServicePlan.sort_order.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_plans_by_type(
        self, 
        plan_type: PlanType, 
        limit: Optional[int] = None
    ) -> List[ServicePlan]:
        """Get plans by type."""
        query = select(ServicePlan).where(
            ServicePlan.plan_type == plan_type,
            ServicePlan.status == PlanStatus.ACTIVE
        ).order_by(ServicePlan.sort_order.asc())
        
        if limit:
            query = query.limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_plan_stats(self, plan_id: int) -> Dict[str, Any]:
        """Get plan statistics."""
        plan = await self.get_by_id(plan_id)
        if not plan:
            return {}

        # Get subscription count
        from app.models.subscription import Subscription
        result = await self.db.execute(
            select(func.count(Subscription.id)).where(Subscription.plan_id == plan_id)
        )
        total_subscriptions = result.scalar() or 0

        # Get active subscriptions count
        result = await self.db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.plan_id == plan_id,
                Subscription.status == "active"
            )
        )
        active_subscriptions = result.scalar() or 0

        return {
            "plan_id": plan_id,
            "plan_name": plan.name,
            "total_subscriptions": total_subscriptions,
            "active_subscriptions": active_subscriptions,
            "inactive_subscriptions": total_subscriptions - active_subscriptions,
            "revenue": float(plan.price * active_subscriptions),  # Monthly revenue
        }
