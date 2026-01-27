"""Licence analytics and reporting operations.

This module handles analytics, statistics, and dashboard data for licences,
separated from the main licence service for maintainability.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.models.licence import (
    Licence,
    LicenceType,
    LicenceStatus,
    LicenceUsageLog,
    LicencePayment,
    LicenceAlert,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class AnalyticsOperations:
    """Analytics and reporting operations for licences."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_analytics(self, licence_id: int) -> Dict[str, Any]:
        """Get comprehensive analytics for a licence."""
        try:
            # Get licence
            result = await self.db.execute(
                select(Licence).where(Licence.id == licence_id)
            )
            licence = result.scalar_one_or_none()

            if not licence:
                return {"error": "Licence not found"}

            # Get usage logs for the past 30 days
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            usage_result = await self.db.execute(
                select(LicenceUsageLog)
                .where(LicenceUsageLog.licence_id == licence_id)
                .where(LicenceUsageLog.recorded_at >= thirty_days_ago)
                .order_by(LicenceUsageLog.recorded_at.desc())
            )
            usage_logs = usage_result.scalars().all()

            # Get payment history
            payment_result = await self.db.execute(
                select(LicencePayment)
                .where(LicencePayment.licence_id == licence_id)
                .order_by(LicencePayment.created_at.desc())
                .limit(10)
            )
            payments = payment_result.scalars().all()

            # Calculate metrics
            usage_trend = self._calculate_usage_trend(usage_logs)
            revenue_metrics = await self._calculate_revenue_metrics(licence_id)
            growth_metrics = self._calculate_growth_metrics(usage_logs)

            return {
                "licence_id": licence_id,
                "licence_type": licence.licence_type.value if licence.licence_type else None,
                "status": licence.status.value if licence.status else None,
                "usage_trend": usage_trend,
                "revenue": revenue_metrics,
                "growth": growth_metrics,
                "recent_payments": [
                    {
                        "id": p.id,
                        "amount": float(p.amount) if p.amount else 0,
                        "status": p.status,
                        "created_at": p.created_at.isoformat() if p.created_at else None,
                    }
                    for p in payments
                ],
                "generated_at": datetime.utcnow().isoformat(),
            }

        except SQLAlchemyError as e:
            logger.error(f"Database error getting analytics for licence {licence_id}: {e}")
            return {"error": str(e)}

    async def get_dashboard_data(self, licence_id: int) -> Dict[str, Any]:
        """Get dashboard data for a licence."""
        try:
            # Get licence
            result = await self.db.execute(
                select(Licence).where(Licence.id == licence_id)
            )
            licence = result.scalar_one_or_none()

            if not licence:
                return {"error": "Licence not found"}

            # Get current usage
            current_usage = await self._get_current_usage(licence_id)

            # Get recent alerts
            alerts_result = await self.db.execute(
                select(LicenceAlert)
                .where(LicenceAlert.licence_id == licence_id)
                .where(LicenceAlert.is_acknowledged == False)
                .order_by(LicenceAlert.created_at.desc())
                .limit(5)
            )
            alerts = alerts_result.scalars().all()

            # Calculate days until expiry
            days_until_expiry = None
            if licence.expires_at:
                delta = licence.expires_at - datetime.utcnow()
                days_until_expiry = max(0, delta.days)

            return {
                "licence": {
                    "id": licence.id,
                    "key": licence.licence_key,
                    "type": licence.licence_type.value if licence.licence_type else None,
                    "status": licence.status.value if licence.status else None,
                    "expires_at": licence.expires_at.isoformat() if licence.expires_at else None,
                    "days_until_expiry": days_until_expiry,
                },
                "usage": current_usage,
                "alerts": [
                    {
                        "id": a.id,
                        "type": a.alert_type,
                        "message": a.message,
                        "severity": a.severity,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in alerts
                ],
                "generated_at": datetime.utcnow().isoformat(),
            }

        except SQLAlchemyError as e:
            logger.error(f"Database error getting dashboard for licence {licence_id}: {e}")
            return {"error": str(e)}

    async def get_earnings(
        self,
        licence_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get earnings report for licences."""
        try:
            query = select(LicencePayment).where(LicencePayment.status == "completed")

            if licence_id:
                query = query.where(LicencePayment.licence_id == licence_id)

            if start_date:
                query = query.where(LicencePayment.created_at >= start_date)
            if end_date:
                query = query.where(LicencePayment.created_at <= end_date)

            result = await self.db.execute(query)
            payments = result.scalars().all()

            total_amount = sum(float(p.amount) for p in payments if p.amount)
            payment_count = len(payments)

            # Group by month
            monthly_earnings = {}
            for payment in payments:
                if payment.created_at:
                    month_key = payment.created_at.strftime("%Y-%m")
                    if month_key not in monthly_earnings:
                        monthly_earnings[month_key] = 0
                    monthly_earnings[month_key] += float(payment.amount) if payment.amount else 0

            return {
                "total_amount": total_amount,
                "payment_count": payment_count,
                "average_payment": total_amount / payment_count if payment_count > 0 else 0,
                "monthly_breakdown": monthly_earnings,
                "period": {
                    "start": start_date.isoformat() if start_date else None,
                    "end": end_date.isoformat() if end_date else None,
                },
                "generated_at": datetime.utcnow().isoformat(),
            }

        except SQLAlchemyError as e:
            logger.error(f"Database error getting earnings: {e}")
            return {"error": str(e)}

    async def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics for all licences."""
        try:
            # Total licences by status
            status_query = (
                select(Licence.status, func.count())
                .group_by(Licence.status)
            )
            status_result = await self.db.execute(status_query)
            by_status = {row[0].value if row[0] else "unknown": row[1] for row in status_result.all()}

            # Total licences by type
            type_query = (
                select(Licence.licence_type, func.count())
                .group_by(Licence.licence_type)
            )
            type_result = await self.db.execute(type_query)
            by_type = {row[0].value if row[0] else "unknown": row[1] for row in type_result.all()}

            # Expiring soon (next 30 days)
            thirty_days = datetime.utcnow() + timedelta(days=30)
            expiring_query = select(func.count()).select_from(
                select(Licence)
                .where(Licence.expires_at <= thirty_days)
                .where(Licence.expires_at > datetime.utcnow())
                .where(Licence.status == LicenceStatus.ACTIVE)
                .subquery()
            )
            expiring_result = await self.db.execute(expiring_query)
            expiring_soon = expiring_result.scalar() or 0

            # Total revenue
            revenue_query = select(func.sum(LicencePayment.amount)).where(
                LicencePayment.status == "completed"
            )
            revenue_result = await self.db.execute(revenue_query)
            total_revenue = float(revenue_result.scalar() or 0)

            return {
                "by_status": by_status,
                "by_type": by_type,
                "expiring_soon": expiring_soon,
                "total_revenue": total_revenue,
                "generated_at": datetime.utcnow().isoformat(),
            }

        except SQLAlchemyError as e:
            logger.error(f"Database error getting summary stats: {e}")
            return {"error": str(e)}

    def _calculate_usage_trend(self, usage_logs: List[LicenceUsageLog]) -> Dict[str, Any]:
        """Calculate usage trend from logs."""
        if not usage_logs:
            return {"trend": "stable", "change_percentage": 0}

        # Get first and last week averages
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        recent_logs = [l for l in usage_logs if l.recorded_at and l.recorded_at >= week_ago]
        older_logs = [l for l in usage_logs if l.recorded_at and two_weeks_ago <= l.recorded_at < week_ago]

        recent_avg = sum(l.active_users or 0 for l in recent_logs) / len(recent_logs) if recent_logs else 0
        older_avg = sum(l.active_users or 0 for l in older_logs) / len(older_logs) if older_logs else 0

        if older_avg == 0:
            return {"trend": "stable", "change_percentage": 0}

        change = ((recent_avg - older_avg) / older_avg) * 100

        if change > 5:
            trend = "increasing"
        elif change < -5:
            trend = "decreasing"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "change_percentage": round(change, 2),
            "recent_average": round(recent_avg, 2),
            "previous_average": round(older_avg, 2),
        }

    async def _calculate_revenue_metrics(self, licence_id: int) -> Dict[str, Any]:
        """Calculate revenue metrics for a licence."""
        try:
            # Get all completed payments
            result = await self.db.execute(
                select(LicencePayment)
                .where(LicencePayment.licence_id == licence_id)
                .where(LicencePayment.status == "completed")
            )
            payments = result.scalars().all()

            total = sum(float(p.amount) for p in payments if p.amount)

            # Last 30 days
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            recent_payments = [p for p in payments if p.created_at and p.created_at >= thirty_days_ago]
            recent_total = sum(float(p.amount) for p in recent_payments if p.amount)

            return {
                "total_revenue": total,
                "last_30_days": recent_total,
                "payment_count": len(payments),
            }

        except SQLAlchemyError:
            return {"total_revenue": 0, "last_30_days": 0, "payment_count": 0}

    def _calculate_growth_metrics(self, usage_logs: List[LicenceUsageLog]) -> Dict[str, Any]:
        """Calculate growth metrics from usage logs."""
        if not usage_logs:
            return {"user_growth": 0, "router_growth": 0}

        # Sort by date
        sorted_logs = sorted(usage_logs, key=lambda l: l.recorded_at or datetime.min)

        if len(sorted_logs) < 2:
            return {"user_growth": 0, "router_growth": 0}

        oldest = sorted_logs[0]
        newest = sorted_logs[-1]

        user_growth = (newest.active_users or 0) - (oldest.active_users or 0)
        router_growth = (newest.active_routers or 0) - (oldest.active_routers or 0)

        return {
            "user_growth": user_growth,
            "router_growth": router_growth,
            "period_days": (newest.recorded_at - oldest.recorded_at).days if newest.recorded_at and oldest.recorded_at else 0,
        }

    async def _get_current_usage(self, licence_id: int) -> Dict[str, Any]:
        """Get current usage statistics for a licence."""
        try:
            # Get most recent usage log
            result = await self.db.execute(
                select(LicenceUsageLog)
                .where(LicenceUsageLog.licence_id == licence_id)
                .order_by(LicenceUsageLog.recorded_at.desc())
                .limit(1)
            )
            log = result.scalar_one_or_none()

            if not log:
                return {
                    "active_users": 0,
                    "active_routers": 0,
                    "api_calls_today": 0,
                    "last_updated": None,
                }

            return {
                "active_users": log.active_users or 0,
                "active_routers": log.active_routers or 0,
                "api_calls_today": log.api_calls or 0,
                "last_updated": log.recorded_at.isoformat() if log.recorded_at else None,
            }

        except SQLAlchemyError:
            return {
                "active_users": 0,
                "active_routers": 0,
                "api_calls_today": 0,
                "last_updated": None,
            }
