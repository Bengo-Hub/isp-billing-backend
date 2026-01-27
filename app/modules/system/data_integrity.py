"""Data integrity service for identifying and fixing database inconsistencies."""

from typing import Dict, List, Any
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.user import User
from app.models.subscription import Subscription
from app.models.billing import Invoice, Payment
from app.models.plan import ServicePlan
from app.models.router import Router


class DataIntegrityService:
    """Service for identifying and fixing data integrity issues."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def check_orphaned_records(self) -> Dict[str, List[Dict[str, Any]]]:
        """Check for orphaned records across all tables."""
        issues = {
            "orphaned_subscriptions": [],
            "orphaned_invoices": [],
            "orphaned_payments": [],
            "missing_plans": [],
            "missing_routers": []
        }

        # Check for subscriptions with non-existent users
        orphaned_subscriptions_query = select(Subscription).where(
            ~Subscription.user_id.in_(select(User.id))
        )
        result = await self.db.execute(orphaned_subscriptions_query)
        orphaned_subscriptions = result.scalars().all()
        
        for sub in orphaned_subscriptions:
            issues["orphaned_subscriptions"].append({
                "subscription_id": sub.id,
                "user_id": sub.user_id,
                "username": sub.username,
                "status": sub.status.value
            })

        # Check for invoices with non-existent users
        orphaned_invoices_query = select(Invoice).where(
            ~Invoice.user_id.in_(select(User.id))
        )
        result = await self.db.execute(orphaned_invoices_query)
        orphaned_invoices = result.scalars().all()
        
        for invoice in orphaned_invoices:
            issues["orphaned_invoices"].append({
                "invoice_id": invoice.id,
                "user_id": invoice.user_id,
                "invoice_number": invoice.invoice_number,
                "total_amount": float(invoice.total_amount)
            })

        # Check for payments with non-existent users
        orphaned_payments_query = select(Payment).where(
            ~Payment.user_id.in_(select(User.id))
        )
        result = await self.db.execute(orphaned_payments_query)
        orphaned_payments = result.scalars().all()
        
        for payment in orphaned_payments:
            issues["orphaned_payments"].append({
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "amount": float(payment.amount)
            })

        # Check for subscriptions with non-existent plans
        missing_plans_query = select(Subscription).where(
            ~Subscription.plan_id.in_(select(ServicePlan.id))
        )
        result = await self.db.execute(missing_plans_query)
        missing_plans = result.scalars().all()
        
        for sub in missing_plans:
            issues["missing_plans"].append({
                "subscription_id": sub.id,
                "plan_id": sub.plan_id,
                "username": sub.username
            })

        # Check for subscriptions with non-existent routers
        missing_routers_query = select(Subscription).where(
            ~Subscription.router_id.in_(select(Router.id))
        )
        result = await self.db.execute(missing_routers_query)
        missing_routers = result.scalars().all()
        
        for sub in missing_routers:
            issues["missing_routers"].append({
                "subscription_id": sub.id,
                "router_id": sub.router_id,
                "username": sub.username
            })

        return issues

    async def get_integrity_summary(self) -> Dict[str, Any]:
        """Get a summary of data integrity issues."""
        issues = await self.check_orphaned_records()
        
        summary = {
            "total_issues": sum(len(issue_list) for issue_list in issues.values()),
            "issues_by_type": {key: len(value) for key, value in issues.items()},
            "details": issues
        }
        
        return summary

    async def fix_orphaned_subscriptions(self, dry_run: bool = True) -> Dict[str, Any]:
        """Fix orphaned subscriptions by marking them as inactive."""
        issues = await self.check_orphaned_records()
        orphaned_subs = issues["orphaned_subscriptions"]
        
        if not orphaned_subs:
            return {"message": "No orphaned subscriptions found", "fixed": 0}
        
        if dry_run:
            return {
                "message": f"Found {len(orphaned_subs)} orphaned subscriptions",
                "would_fix": len(orphaned_subs),
                "details": orphaned_subs
            }
        
        # Actually fix the issues
        fixed_count = 0
        for sub_info in orphaned_subs:
            subscription = await self.db.get(Subscription, sub_info["subscription_id"])
            if subscription:
                subscription.status = "CANCELLED"  # Mark as cancelled instead of deleting
                subscription.notes = f"Auto-cancelled due to missing user {sub_info['user_id']}"
                fixed_count += 1
        
        await self.db.commit()
        
        return {
            "message": f"Fixed {fixed_count} orphaned subscriptions",
            "fixed": fixed_count
        }

    async def log_integrity_issues(self) -> None:
        """Log all integrity issues for monitoring."""
        summary = await self.get_integrity_summary()
        
        if summary["total_issues"] > 0:
            self.logger.warning(f"Data integrity issues found: {summary['issues_by_type']}")
            for issue_type, details in summary["details"].items():
                if details:
                    self.logger.warning(f"{issue_type}: {len(details)} issues")
                    for detail in details[:5]:  # Log first 5 of each type
                        self.logger.warning(f"  {detail}")
        else:
            self.logger.info("No data integrity issues found")
