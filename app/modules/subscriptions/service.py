"""Subscription management service."""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import (
    Subscription, 
    SubscriptionUsageLog, 
    SubscriptionHistory,
    SubscriptionStatus, 
    SubscriptionType
)
from app.models.user import User
from app.models.plan import ServicePlan
from app.models.router import Router
from app.api.deps import PaginationParams
from app.core.datetime_utils import normalize_datetime


class SubscriptionService:
    """Subscription management service."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, subscription_id: int) -> Optional[Subscription]:
        """Get subscription by ID."""
        return await self.db.get(Subscription, subscription_id)

    async def get_all(
        self,
        pagination: PaginationParams,
        user_id: Optional[int] = None,
        plan_id: Optional[int] = None,
        router_id: Optional[int] = None,
        status: Optional[SubscriptionStatus] = None,
        subscription_type: Optional[SubscriptionType] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all subscriptions with pagination and filters."""
        query = select(Subscription)

        # Apply filters
        if user_id:
            query = query.where(Subscription.user_id == user_id)
        if plan_id:
            query = query.where(Subscription.plan_id == plan_id)
        if router_id:
            query = query.where(Subscription.router_id == router_id)
        if status:
            query = query.where(Subscription.status == status)
        if subscription_type:
            query = query.where(Subscription.subscription_type == subscription_type)
        if search:
            search_term = f"%{search}%"
            query = query.where(Subscription.username.ilike(search_term))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get subscriptions with pagination
        query = query.order_by(Subscription.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        subscriptions = result.scalars().all()

        return {
            "subscriptions": subscriptions,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_subscription(
        self,
        user_id: int,
        plan_id: int,
        router_id: int,
        subscription_type: SubscriptionType,
        username: str,
        password: str,
        start_date: datetime,
        end_date: datetime,
        is_auto_renewal: bool = False,
        created_by: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Subscription:
        """Create a new subscription."""
        # Validate user exists
        user = await self.db.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        # Validate plan exists
        plan = await self.db.get(ServicePlan, plan_id)
        if not plan:
            raise ValueError("Service plan not found")

        # Validate router exists
        router = await self.db.get(Router, router_id)
        if not router:
            raise ValueError("Router not found")

        # Check for existing subscription
        existing = await self.db.execute(
            select(Subscription).where(
                and_(
                    Subscription.user_id == user_id,
                    Subscription.router_id == router_id,
                    Subscription.subscription_type == subscription_type
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("User already has a subscription on this router")

        subscription = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            router_id=router_id,
            subscription_type=subscription_type,
            username=username,
            password=password,
            start_date=start_date,
            end_date=end_date,
            is_auto_renewal=is_auto_renewal,
            created_by=created_by,
            notes=notes,
            status=SubscriptionStatus.PENDING,
        )

        self.db.add(subscription)
        await self.db.commit()
        await self.db.refresh(subscription)

        # Log subscription creation
        await self._log_subscription_action(
            subscription.id,
            "created",
            f"Subscription created for user {user.username}",
            created_by
        )

        return subscription

    async def update_subscription(
        self, 
        subscription_id: int, 
        update_data: Dict[str, Any],
        updated_by: Optional[int] = None
    ) -> Optional[Subscription]:
        """Update subscription."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return None

        old_status = subscription.status.value if subscription.status else None

        # Update fields
        for field, value in update_data.items():
            if hasattr(subscription, field) and value is not None:
                setattr(subscription, field, value)

        await self.db.commit()
        await self.db.refresh(subscription)

        # Log status change if applicable
        if old_status and subscription.status.value != old_status:
            await self._log_subscription_action(
                subscription_id,
                "status_changed",
                f"Status changed from {old_status} to {subscription.status.value}",
                updated_by
            )

        return subscription

    async def activate_subscription(
        self, 
        subscription_id: int, 
        activated_by: Optional[int] = None
    ) -> Optional[Subscription]:
        """Activate subscription."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return None

        subscription.status = SubscriptionStatus.ACTIVE
        await self.db.commit()
        await self.db.refresh(subscription)

        await self._log_subscription_action(
            subscription_id,
            "activated",
            "Subscription activated",
            activated_by
        )

        return subscription

    async def suspend_subscription(
        self, 
        subscription_id: int, 
        suspended_by: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Optional[Subscription]:
        """Suspend subscription."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return None

        subscription.status = SubscriptionStatus.SUSPENDED
        await self.db.commit()
        await self.db.refresh(subscription)

        await self._log_subscription_action(
            subscription_id,
            "suspended",
            f"Subscription suspended. Reason: {reason or 'No reason provided'}",
            suspended_by
        )

        return subscription

    async def cancel_subscription(
        self, 
        subscription_id: int, 
        cancelled_by: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Optional[Subscription]:
        """Cancel subscription."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return None

        subscription.status = SubscriptionStatus.CANCELLED
        await self.db.commit()
        await self.db.refresh(subscription)

        await self._log_subscription_action(
            subscription_id,
            "cancelled",
            f"Subscription cancelled. Reason: {reason or 'No reason provided'}",
            cancelled_by
        )

        return subscription

    async def delete_subscription(
        self, 
        subscription_id: int, 
        deleted_by: Optional[int] = None
    ) -> bool:
        """Delete subscription (soft delete by setting status to cancelled)."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return False

        # Soft delete by setting status to cancelled
        subscription.status = SubscriptionStatus.CANCELLED
        await self.db.commit()

        await self._log_subscription_action(
            subscription_id,
            "deleted",
            "Subscription deleted",
            deleted_by
        )

        return True

    async def get_user_subscriptions(
        self, 
        user_id: int, 
        active_only: bool = False
    ) -> List[Subscription]:
        """Get subscriptions for a specific user."""
        query = select(Subscription).where(Subscription.user_id == user_id)
        
        if active_only:
            query = query.where(Subscription.status == SubscriptionStatus.ACTIVE)
        
        query = query.order_by(Subscription.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_expired_subscriptions(self) -> List[Subscription]:
        """Get expired subscriptions."""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(Subscription).where(
                and_(
                    Subscription.end_date < now,
                    Subscription.status.in_([
                        SubscriptionStatus.ACTIVE,
                        SubscriptionStatus.PENDING
                    ])
                )
            )
        )
        return result.scalars().all()

    async def get_expiring_subscriptions(self, days: int = 7) -> List[Subscription]:
        """Get subscriptions expiring within specified days."""
        now = datetime.utcnow()
        expiry_date = now + timedelta(days=days)
        
        result = await self.db.execute(
            select(Subscription).where(
                and_(
                    Subscription.end_date <= expiry_date,
                    Subscription.end_date > now,
                    Subscription.status == SubscriptionStatus.ACTIVE
                )
            )
        )
        return result.scalars().all()

    async def renew_subscription(
        self, 
        subscription_id: int, 
        new_end_date: datetime,
        renewed_by: Optional[int] = None
    ) -> Optional[Subscription]:
        """Renew subscription."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return None

        old_end_date = subscription.end_date
        subscription.end_date = new_end_date
        subscription.status = SubscriptionStatus.ACTIVE
        
        await self.db.commit()
        await self.db.refresh(subscription)

        await self._log_subscription_action(
            subscription_id,
            "renewed",
            f"Subscription renewed from {old_end_date} to {new_end_date}",
            renewed_by
        )

        return subscription

    async def update_usage(
        self,
        subscription_id: int,
        bytes_uploaded: int,
        bytes_downloaded: int,
        session_duration: int = 0,
        ip_address: Optional[str] = None,
        mac_address: Optional[str] = None,
    ) -> bool:
        """Update subscription usage."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return False

        # Update subscription usage
        subscription.bytes_uploaded += bytes_uploaded
        subscription.bytes_downloaded += bytes_downloaded
        subscription.total_bytes_used += bytes_uploaded + bytes_downloaded
        subscription.session_count += 1
        subscription.last_activity = datetime.utcnow()

        # Create usage log entry
        usage_log = SubscriptionUsageLog(
            subscription_id=subscription_id,
            log_date=datetime.utcnow(),
            bytes_uploaded=bytes_uploaded,
            bytes_downloaded=bytes_downloaded,
            session_duration=session_duration,
            ip_address=ip_address,
            mac_address=mac_address,
        )

        self.db.add(usage_log)
        await self.db.commit()

        return True

    async def get_usage_logs(
        self, 
        subscription_id: int, 
        limit: int = 100
    ) -> List[SubscriptionUsageLog]:
        """Get usage logs for subscription."""
        result = await self.db.execute(
            select(SubscriptionUsageLog)
            .where(SubscriptionUsageLog.subscription_id == subscription_id)
            .order_by(SubscriptionUsageLog.log_date.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_subscription_history(
        self, 
        subscription_id: int
    ) -> List[SubscriptionHistory]:
        """Get subscription history."""
        result = await self.db.execute(
            select(SubscriptionHistory)
            .where(SubscriptionHistory.subscription_id == subscription_id)
            .order_by(SubscriptionHistory.created_at.desc())
        )
        return result.scalars().all()

    async def get_subscription_stats(self, subscription_id: int) -> Dict[str, Any]:
        """Get subscription statistics."""
        subscription = await self.get_by_id(subscription_id)
        if not subscription:
            return {}

        # Get usage logs for the last 30 days
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        result = await self.db.execute(
            select(func.sum(SubscriptionUsageLog.bytes_uploaded), func.sum(SubscriptionUsageLog.bytes_downloaded))
            .where(
                and_(
                    SubscriptionUsageLog.subscription_id == subscription_id,
                    SubscriptionUsageLog.log_date >= thirty_days_ago
                )
            )
        )
        usage_data = result.first()
        
        monthly_uploaded = usage_data[0] or 0
        monthly_downloaded = usage_data[1] or 0

        return {
            "subscription_id": subscription_id,
            "username": subscription.username,
            "status": subscription.status.value,
            "total_bytes_used": subscription.total_bytes_used,
            "total_data_used_gb": subscription.total_data_used_gb,
            "session_count": subscription.session_count,
            "monthly_uploaded": monthly_uploaded,
            "monthly_downloaded": monthly_downloaded,
            "last_activity": subscription.last_activity,
            "start_date": normalize_datetime(subscription.start_date),
            "end_date": normalize_datetime(subscription.end_date),
            "is_active": subscription.is_active,
            "is_expired": subscription.is_expired,
        }

    async def _log_subscription_action(
        self,
        subscription_id: int,
        action: str,
        details: str,
        user_id: Optional[int] = None,
    ) -> None:
        """Log subscription action."""
        history = SubscriptionHistory(
            subscription_id=subscription_id,
            action=action,
            details=details,
            changed_by=user_id,
        )
        
        self.db.add(history)
        await self.db.commit()
