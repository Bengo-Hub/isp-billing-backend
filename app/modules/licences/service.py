"""CodeVertex licence management service with production-ready features."""

import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, ConfigurationError
from app.models.licence import (
    Licence,
    LicencePayment,
    LicenceUsageLog,
    LicenceFeature,
    LicenceAlert,
    LicenceStatus,
    LicenceType,
    LicencePaymentStatus
)
from app.models.router import Router
from app.models.user import User
from app.models.subscription import Subscription
from app.models.billing import Payment
from app.api.deps import PaginationParams

logger = get_logger(__name__)


class LicenceService:
    """Production-ready licence management service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    def _generate_licence_key(self, licence_type: LicenceType) -> str:
        """Generate a unique licence key."""
        prefix_map = {
            LicenceType.TRIAL: "TRL",
            LicenceType.BASIC: "BSC",
            LicenceType.PROFESSIONAL: "PRO",
            LicenceType.ENTERPRISE: "ENT",
            LicenceType.CUSTOM: "CST"
        }
        
        prefix = prefix_map.get(licence_type, "LIC")
        timestamp = datetime.utcnow().strftime("%Y%m")
        random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        
        return f"{prefix}-{timestamp}-{random_part}"

    async def create_licence(
        self,
        licence_data: Dict[str, Any],
        created_by: Optional[int] = None
    ) -> Licence:
        """Create a new licence."""
        try:
            # Generate unique licence key
            licence_key = self._generate_licence_key(licence_data['licence_type'])
            
            # Ensure licence key is unique
            while await self._licence_key_exists(licence_key):
                licence_key = self._generate_licence_key(licence_data['licence_type'])

            # Set default dates if not provided
            if 'issue_date' not in licence_data:
                licence_data['issue_date'] = datetime.utcnow()
            
            if 'expiry_date' not in licence_data:
                # Default to 1 month for new licences
                licence_data['expiry_date'] = datetime.utcnow() + timedelta(days=30)

            # Set default features based on licence type
            if 'features' not in licence_data:
                licence_data['features'] = await self._get_default_features(licence_data['licence_type'])

            licence = Licence(
                licence_key=licence_key,
                **licence_data
            )

            self.db.add(licence)
            await self.db.commit()
            await self.db.refresh(licence)

            # Create initial usage log
            await self._create_initial_usage_log(licence.id)

            # Create welcome alert
            await self._create_welcome_alert(licence.id)

            self.logger.info(f"Created licence {licence_key} for {licence_data['contact_email']}")
            return licence

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to create licence: {e}")
            raise

    async def get_licence_by_id(self, licence_id: int) -> Optional[Licence]:
        """Get licence by ID."""
        return await self.db.get(Licence, licence_id)

    async def get_licence_by_key(self, licence_key: str) -> Optional[Licence]:
        """Get licence by licence key."""
        result = await self.db.execute(
            select(Licence).where(Licence.licence_key == licence_key)
        )
        return result.scalar_one_or_none()

    async def get_all_licences(
        self,
        pagination: PaginationParams,
        status: Optional[LicenceStatus] = None,
        licence_type: Optional[LicenceType] = None,
        search: Optional[str] = None,
        expiring_soon: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Get all licences with filtering and pagination."""
        query = select(Licence)

        # Apply filters
        if status:
            query = query.where(Licence.status == status)
        if licence_type:
            query = query.where(Licence.licence_type == licence_type)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    Licence.licence_name.ilike(search_term),
                    Licence.licence_key.ilike(search_term),
                    Licence.organization_name.ilike(search_term),
                    Licence.contact_email.ilike(search_term)
                )
            )
        if expiring_soon:
            expiry_threshold = datetime.utcnow() + timedelta(days=30)
            query = query.where(Licence.expiry_date <= expiry_threshold)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get licences with pagination
        query = query.order_by(desc(Licence.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        licences = result.scalars().all()

        return {
            "items": licences,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size
        }

    async def update_licence(self, licence_id: int, updates: Dict[str, Any]) -> Optional[Licence]:
        """Update a licence."""
        licence = await self.get_licence_by_id(licence_id)
        if not licence:
            return None

        try:
            # Track significant changes
            significant_changes = []
            
            for key, value in updates.items():
                if hasattr(licence, key):
                    old_value = getattr(licence, key)
                    setattr(licence, key, value)
                    
                    # Track important changes
                    if key in ['status', 'expiry_date', 'max_routers', 'max_users']:
                        significant_changes.append(f"{key}: {old_value} -> {value}")

            await self.db.commit()
            await self.db.refresh(licence)

            # Log significant changes
            if significant_changes:
                await self._create_change_alert(licence_id, significant_changes)

            self.logger.info(f"Updated licence {licence.licence_key}: {', '.join(significant_changes)}")
            return licence

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to update licence {licence_id}: {e}")
            raise

    async def renew_licence(
        self,
        licence_id: int,
        renewal_months: int,
        payment_method: str,
        amount: Decimal,
        auto_renewal: bool = True
    ) -> Dict[str, Any]:
        """Renew a licence subscription."""
        licence = await self.get_licence_by_id(licence_id)
        if not licence:
            raise ValidationError(f"Licence {licence_id} not found")

        try:
            # Calculate new expiry date
            current_expiry = licence.expiry_date
            if licence.is_expired:
                # If expired, start from now
                new_expiry = datetime.utcnow() + timedelta(days=30 * renewal_months)
            else:
                # If active, extend from current expiry
                new_expiry = current_expiry + timedelta(days=30 * renewal_months)

            # Generate payment reference
            payment_ref = f"LIC-{licence.licence_key}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            # Create payment record
            payment = LicencePayment(
                licence_id=licence_id,
                payment_reference=payment_ref,
                amount=amount,
                currency=licence.currency,
                payment_method=payment_method,
                billing_period_start=current_expiry if not licence.is_expired else datetime.utcnow(),
                billing_period_end=new_expiry,
                extends_licence_until=new_expiry,
                is_renewal=True,
                status=LicencePaymentStatus.PENDING
            )

            self.db.add(payment)

            # Update licence
            licence.auto_renewal_enabled = auto_renewal
            licence.last_renewal_date = datetime.utcnow()

            await self.db.commit()
            await self.db.refresh(payment)

            # Create renewal alert
            await self._create_renewal_alert(licence_id, new_expiry)

            return {
                "payment_reference": payment_ref,
                "amount": amount,
                "new_expiry_date": new_expiry,
                "payment_id": payment.id,
                "status": "pending_payment"
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to renew licence {licence_id}: {e}")
            raise

    async def process_licence_payment(
        self,
        payment_reference: str,
        external_transaction_id: str,
        gateway_response: Optional[str] = None
    ) -> bool:
        """Process a licence payment and update licence status."""
        try:
            # Get payment record
            result = await self.db.execute(
                select(LicencePayment).where(LicencePayment.payment_reference == payment_reference)
            )
            payment = result.scalar_one_or_none()
            
            if not payment:
                self.logger.error(f"Payment record not found: {payment_reference}")
                return False

            # Update payment status
            payment.status = LicencePaymentStatus.COMPLETED
            payment.payment_date = datetime.utcnow()
            payment.processed_date = datetime.utcnow()
            payment.external_transaction_id = external_transaction_id
            payment.gateway_response = gateway_response

            # Update licence
            licence = await self.get_licence_by_id(payment.licence_id)
            if licence and payment.extends_licence_until:
                licence.expiry_date = payment.extends_licence_until
                licence.status = LicenceStatus.ACTIVE

                # Clear expiry alerts
                await self._clear_expiry_alerts(licence.id)

            await self.db.commit()

            self.logger.info(f"Processed licence payment {payment_reference} for licence {licence.licence_key}")
            return True

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to process licence payment {payment_reference}: {e}")
            return False

    async def check_licence_status(self, licence_key: str) -> Dict[str, Any]:
        """Check licence status and return detailed information."""
        licence = await self.get_licence_by_key(licence_key)
        if not licence:
            return {
                "is_valid": False,
                "error": "Licence not found"
            }

        # Get current usage
        current_usage = await self._get_current_usage(licence.id)
        
        # Check feature availability
        available_features = await self._get_available_features(licence)
        
        # Get warnings and errors
        warnings = []
        errors = []
        
        if licence.is_near_expiry:
            warnings.append(f"Licence expires in {licence.days_until_expiry} days")
        
        if licence.is_expired:
            errors.append("Licence has expired")
        
        if current_usage.get('routers', 0) >= licence.max_routers:
            warnings.append("Router limit reached")
        
        if current_usage.get('users', 0) >= licence.max_users:
            warnings.append("User limit reached")

        return {
            "licence_key": licence_key,
            "status": licence.status.value,
            "is_valid": licence.status == LicenceStatus.ACTIVE and not licence.is_expired,
            "expiry_date": licence.expiry_date,
            "days_remaining": licence.days_until_expiry,
            "features_available": available_features,
            "usage_limits": {
                "max_routers": licence.max_routers,
                "max_users": licence.max_users,
                "max_concurrent_sessions": licence.max_concurrent_sessions
            },
            "current_usage": current_usage,
            "warnings": warnings,
            "errors": errors
        }

    async def get_licence_earnings(
        self,
        licence_id: int,
        period_type: str = "monthly",
        months: int = 6
    ) -> Dict[str, Any]:
        """Get licence earnings data."""
        licence = await self.get_licence_by_id(licence_id)
        if not licence:
            raise ValidationError(f"Licence {licence_id} not found")

        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30 * months)

        # Get usage logs for the period
        result = await self.db.execute(
            select(LicenceUsageLog)
            .where(
                and_(
                    LicenceUsageLog.licence_id == licence_id,
                    LicenceUsageLog.log_date >= start_date,
                    LicenceUsageLog.log_type == period_type
                )
            )
            .order_by(LicenceUsageLog.log_date.asc())
        )
        usage_logs = result.scalars().all()

        # Process earnings data
        earnings_data = []
        total_revenue = Decimal('0')
        total_transactions = 0

        for log in usage_logs:
            revenue = log.daily_revenue if period_type == "daily" else log.monthly_revenue
            earnings_data.append({
                "date": log.log_date.isoformat(),
                "revenue": float(revenue),
                "transactions": log.total_transactions,
                "users": log.users_count,
                "sms_balance": float(log.sms_balance)
            })
            total_revenue += revenue
            total_transactions += log.total_transactions

        # Calculate growth percentage
        growth_percentage = None
        if len(earnings_data) >= 2:
            recent_revenue = sum(float(item['revenue']) for item in earnings_data[-2:])
            previous_revenue = sum(float(item['revenue']) for item in earnings_data[-4:-2]) if len(earnings_data) >= 4 else 0
            
            if previous_revenue > 0:
                growth_percentage = ((recent_revenue - previous_revenue) / previous_revenue) * 100

        average_transaction_value = total_revenue / total_transactions if total_transactions > 0 else Decimal('0')

        return {
            "licence_id": licence_id,
            "period_type": period_type,
            "earnings_data": earnings_data,
            "total_revenue": float(total_revenue),
            "total_transactions": total_transactions,
            "average_transaction_value": float(average_transaction_value),
            "growth_percentage": round(growth_percentage, 2) if growth_percentage else None
        }

    async def update_licence_usage(
        self,
        licence_id: int,
        usage_data: Dict[str, Any],
        log_type: str = "daily"
    ) -> bool:
        """Update licence usage statistics."""
        try:
            licence = await self.get_licence_by_id(licence_id)
            if not licence:
                return False

            # Get current date for log
            log_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            if log_type == "weekly":
                # Start of week (Monday)
                log_date = log_date - timedelta(days=log_date.weekday())
            elif log_type == "monthly":
                # Start of month
                log_date = log_date.replace(day=1)

            # Check if usage log already exists for this date
            result = await self.db.execute(
                select(LicenceUsageLog).where(
                    and_(
                        LicenceUsageLog.licence_id == licence_id,
                        LicenceUsageLog.log_date == log_date,
                        LicenceUsageLog.log_type == log_type
                    )
                )
            )
            usage_log = result.scalar_one_or_none()

            if usage_log:
                # Update existing log
                for key, value in usage_data.items():
                    if hasattr(usage_log, key):
                        setattr(usage_log, key, value)
            else:
                # Create new log
                usage_log = LicenceUsageLog(
                    licence_id=licence_id,
                    log_date=log_date,
                    log_type=log_type,
                    **usage_data
                )
                self.db.add(usage_log)

            # Update licence current usage
            licence.current_routers = usage_data.get('routers_count', licence.current_routers)
            licence.current_users = usage_data.get('users_count', licence.current_users)
            licence.total_transactions = usage_data.get('total_transactions', licence.total_transactions)

            await self.db.commit()

            # Check for usage limit alerts
            await self._check_usage_limits(licence)

            return True

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to update licence usage {licence_id}: {e}")
            return False

    async def get_licence_analytics(self, licence_id: int) -> Dict[str, Any]:
        """Get comprehensive licence analytics."""
        licence = await self.get_licence_by_id(licence_id)
        if not licence:
            raise ValidationError(f"Licence {licence_id} not found")

        # Get recent usage logs (last 30 days)
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        result = await self.db.execute(
            select(LicenceUsageLog)
            .where(
                and_(
                    LicenceUsageLog.licence_id == licence_id,
                    LicenceUsageLog.log_date >= start_date,
                    LicenceUsageLog.log_type == "daily"
                )
            )
            .order_by(LicenceUsageLog.log_date.desc())
        )
        usage_logs = result.scalars().all()

        # Calculate usage statistics
        usage_statistics = {
            "router_usage_percentage": licence.get_usage_percentage("routers"),
            "user_usage_percentage": licence.get_usage_percentage("users"),
            "average_daily_transactions": sum(log.total_transactions for log in usage_logs) / len(usage_logs) if usage_logs else 0,
            "total_data_transferred_gb": sum(float(log.data_transferred_gb) for log in usage_logs),
            "average_uptime_percentage": sum(float(log.system_uptime_percentage) for log in usage_logs) / len(usage_logs) if usage_logs else 0
        }

        # Calculate revenue metrics
        revenue_metrics = {
            "total_monthly_revenue": sum(float(log.monthly_revenue) for log in usage_logs),
            "average_daily_revenue": sum(float(log.daily_revenue) for log in usage_logs) / len(usage_logs) if usage_logs else 0,
            "sms_balance": float(usage_logs[0].sms_balance) if usage_logs else 0,
            "revenue_trend": self._calculate_revenue_trend(usage_logs)
        }

        # Calculate performance metrics
        performance_metrics = {
            "average_response_time_ms": sum(log.average_response_time_ms for log in usage_logs) / len(usage_logs) if usage_logs else 0,
            "error_rate_percentage": sum(float(log.error_rate_percentage) for log in usage_logs) / len(usage_logs) if usage_logs else 0,
            "api_calls_per_day": sum(log.api_calls_count for log in usage_logs) / len(usage_logs) if usage_logs else 0
        }

        # Get feature usage
        feature_usage = {}
        if usage_logs:
            for log in usage_logs:
                if log.features_used:
                    for feature, usage in log.features_used.items():
                        if feature not in feature_usage:
                            feature_usage[feature] = []
                        feature_usage[feature].append(usage)

        # Get active alerts
        alerts = await self.get_licence_alerts(licence_id, active_only=True)

        # Generate recommendations
        recommendations = await self._generate_recommendations(licence, usage_statistics, revenue_metrics)

        return {
            "licence_id": licence_id,
            "current_status": licence.status.value,
            "days_until_expiry": licence.days_until_expiry,
            "usage_statistics": usage_statistics,
            "revenue_metrics": revenue_metrics,
            "performance_metrics": performance_metrics,
            "feature_usage": feature_usage,
            "alerts": [{"id": alert.id, "type": alert.alert_type, "severity": alert.severity, "message": alert.message} for alert in alerts],
            "recommendations": recommendations
        }

    async def get_licence_alerts(
        self,
        licence_id: int,
        active_only: bool = False
    ) -> List[LicenceAlert]:
        """Get licence alerts."""
        query = select(LicenceAlert).where(LicenceAlert.licence_id == licence_id)
        
        if active_only:
            query = query.where(LicenceAlert.is_active == True)
        
        query = query.order_by(desc(LicenceAlert.created_at))
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def acknowledge_alert(self, alert_id: int, user_id: int) -> bool:
        """Acknowledge a licence alert."""
        try:
            alert = await self.db.get(LicenceAlert, alert_id)
            if not alert:
                return False

            alert.is_acknowledged = True
            alert.acknowledged_by = user_id
            alert.acknowledged_at = datetime.utcnow()

            await self.db.commit()
            return True

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to acknowledge alert {alert_id}: {e}")
            return False

    async def get_dashboard_data(self, licence_id: int) -> Dict[str, Any]:
        """Get licence dashboard data."""
        licence = await self.get_licence_by_id(licence_id)
        if not licence:
            raise ValidationError(f"Licence {licence_id} not found")

        # Get recent payments
        result = await self.db.execute(
            select(LicencePayment)
            .where(LicencePayment.licence_id == licence_id)
            .order_by(desc(LicencePayment.created_at))
            .limit(5)
        )
        recent_payments = result.scalars().all()

        # Get active alerts
        active_alerts = await self.get_licence_alerts(licence_id, active_only=True)

        # Get earnings summary
        earnings = await self.get_licence_earnings(licence_id, "daily", 30)

        # Get current usage
        current_usage = await self._get_current_usage(licence_id)

        # System health metrics
        system_health = {
            "licence_status": licence.status.value,
            "days_until_expiry": licence.days_until_expiry,
            "usage_health": "good" if licence.get_usage_percentage("routers") < 80 else "warning",
            "payment_status": "current" if not licence.is_expired else "overdue"
        }

        # Quick actions
        quick_actions = []
        if licence.is_near_expiry:
            quick_actions.append({"action": "renew", "label": "Renew Licence"})
        if active_alerts:
            quick_actions.append({"action": "view_alerts", "label": f"View {len(active_alerts)} Alerts"})
        quick_actions.append({"action": "view_usage", "label": "View Usage Details"})
        quick_actions.append({"action": "download_report", "label": "Download Report"})

        return {
            "licence_summary": licence,
            "usage_overview": current_usage,
            "recent_payments": recent_payments,
            "active_alerts": [{"id": alert.id, "type": alert.alert_type, "severity": alert.severity, "message": alert.message} for alert in active_alerts],
            "earnings_summary": earnings,
            "system_health": system_health,
            "quick_actions": quick_actions
        }

    # Private helper methods
    async def _licence_key_exists(self, licence_key: str) -> bool:
        """Check if licence key already exists."""
        result = await self.db.execute(
            select(func.count(Licence.id)).where(Licence.licence_key == licence_key)
        )
        return result.scalar() > 0

    async def _get_default_features(self, licence_type: LicenceType) -> Dict[str, Any]:
        """Get default features for licence type."""
        feature_sets = {
            LicenceType.TRIAL: {
                "router_management": True,
                "user_management": True,
                "basic_billing": True,
                "basic_reporting": True,
                "email_notifications": False,
                "sms_notifications": False,
                "advanced_analytics": False,
                "api_access": False
            },
            LicenceType.BASIC: {
                "router_management": True,
                "user_management": True,
                "basic_billing": True,
                "basic_reporting": True,
                "email_notifications": True,
                "sms_notifications": False,
                "advanced_analytics": False,
                "api_access": False
            },
            LicenceType.PROFESSIONAL: {
                "router_management": True,
                "user_management": True,
                "basic_billing": True,
                "advanced_billing": True,
                "basic_reporting": True,
                "advanced_reporting": True,
                "email_notifications": True,
                "sms_notifications": True,
                "advanced_analytics": True,
                "api_access": True,
                "bulk_operations": True
            },
            LicenceType.ENTERPRISE: {
                "router_management": True,
                "user_management": True,
                "basic_billing": True,
                "advanced_billing": True,
                "basic_reporting": True,
                "advanced_reporting": True,
                "email_notifications": True,
                "sms_notifications": True,
                "advanced_analytics": True,
                "api_access": True,
                "bulk_operations": True,
                "white_labeling": True,
                "priority_support": True,
                "custom_integrations": True
            }
        }
        
        return feature_sets.get(licence_type, feature_sets[LicenceType.BASIC])

    async def _create_initial_usage_log(self, licence_id: int) -> None:
        """Create initial usage log for new licence."""
        usage_log = LicenceUsageLog(
            licence_id=licence_id,
            log_date=datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
            log_type="daily"
        )
        self.db.add(usage_log)
        await self.db.commit()

    async def _create_welcome_alert(self, licence_id: int) -> None:
        """Create welcome alert for new licence."""
        alert = LicenceAlert(
            licence_id=licence_id,
            alert_type="welcome",
            severity="low",
            title="Welcome to CodeVertex Billing",
            message="Your licence has been successfully created. Start by configuring your routers and setting up your first service plans.",
            action_required="setup_routers"
        )
        self.db.add(alert)
        await self.db.commit()

    async def _create_renewal_alert(self, licence_id: int, new_expiry: datetime) -> None:
        """Create renewal success alert."""
        alert = LicenceAlert(
            licence_id=licence_id,
            alert_type="renewal_success",
            severity="low",
            title="Licence Renewed Successfully",
            message=f"Your licence has been renewed until {new_expiry.strftime('%Y-%m-%d')}.",
            action_required=None
        )
        self.db.add(alert)
        await self.db.commit()

    async def _create_change_alert(self, licence_id: int, changes: List[str]) -> None:
        """Create alert for significant licence changes."""
        alert = LicenceAlert(
            licence_id=licence_id,
            alert_type="licence_updated",
            severity="medium",
            title="Licence Updated",
            message=f"Your licence has been updated: {', '.join(changes)}",
            action_required=None
        )
        self.db.add(alert)
        await self.db.commit()

    async def _clear_expiry_alerts(self, licence_id: int) -> None:
        """Clear expiry-related alerts."""
        result = await self.db.execute(
            select(LicenceAlert).where(
                and_(
                    LicenceAlert.licence_id == licence_id,
                    LicenceAlert.alert_type.in_(["expiry_warning", "expiry_critical"]),
                    LicenceAlert.is_active == True
                )
            )
        )
        alerts = result.scalars().all()

        for alert in alerts:
            alert.is_active = False

        await self.db.commit()

    async def _get_current_usage(self, licence_id: int) -> Dict[str, Any]:
        """Get current usage statistics."""
        # Get router count
        router_result = await self.db.execute(
            select(func.count(Router.id)).where(Router.is_active == True)
        )
        router_count = router_result.scalar() or 0

        # Get user count
        user_result = await self.db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        user_count = user_result.scalar() or 0

        # Get active subscription count
        subscription_result = await self.db.execute(
            select(func.count(Subscription.id)).where(Subscription.status == "active")
        )
        active_subscriptions = subscription_result.scalar() or 0

        return {
            "routers": router_count,
            "users": user_count,
            "active_subscriptions": active_subscriptions,
            "last_updated": datetime.utcnow().isoformat()
        }

    async def _get_available_features(self, licence: Licence) -> List[str]:
        """Get list of available features for licence."""
        features = licence.get_features()
        return [feature_name for feature_name, enabled in features.items() if enabled]

    async def _check_usage_limits(self, licence: Licence) -> None:
        """Check usage limits and create alerts if needed."""
        router_usage = licence.get_usage_percentage("routers")
        user_usage = licence.get_usage_percentage("users")

        # Router limit alerts
        if router_usage >= 90:
            await self._create_usage_alert(
                licence.id,
                "router_limit",
                "critical" if router_usage >= 100 else "high",
                f"Router limit reached: {licence.current_routers}/{licence.max_routers}"
            )
        elif router_usage >= 80:
            await self._create_usage_alert(
                licence.id,
                "router_limit",
                "medium",
                f"Router limit warning: {licence.current_routers}/{licence.max_routers} ({router_usage:.1f}%)"
            )

        # User limit alerts
        if user_usage >= 90:
            await self._create_usage_alert(
                licence.id,
                "user_limit",
                "critical" if user_usage >= 100 else "high",
                f"User limit reached: {licence.current_users}/{licence.max_users}"
            )
        elif user_usage >= 80:
            await self._create_usage_alert(
                licence.id,
                "user_limit",
                "medium",
                f"User limit warning: {licence.current_users}/{licence.max_users} ({user_usage:.1f}%)"
            )

    async def _create_usage_alert(
        self,
        licence_id: int,
        alert_type: str,
        severity: str,
        message: str
    ) -> None:
        """Create usage limit alert."""
        # Check if similar alert already exists
        result = await self.db.execute(
            select(LicenceAlert).where(
                and_(
                    LicenceAlert.licence_id == licence_id,
                    LicenceAlert.alert_type == alert_type,
                    LicenceAlert.is_active == True
                )
            )
        )
        existing_alert = result.scalar_one_or_none()

        if existing_alert:
            # Update existing alert
            existing_alert.message = message
            existing_alert.severity = severity
            existing_alert.updated_at = datetime.utcnow()
        else:
            # Create new alert
            alert = LicenceAlert(
                licence_id=licence_id,
                alert_type=alert_type,
                severity=severity,
                title=f"{alert_type.replace('_', ' ').title()} Alert",
                message=message,
                action_required="upgrade_licence" if severity == "critical" else None
            )
            self.db.add(alert)

        await self.db.commit()

    def _calculate_revenue_trend(self, usage_logs: List[LicenceUsageLog]) -> str:
        """Calculate revenue trend from usage logs."""
        if len(usage_logs) < 7:
            return "insufficient_data"

        recent_revenue = sum(float(log.daily_revenue) for log in usage_logs[:7])
        previous_revenue = sum(float(log.daily_revenue) for log in usage_logs[7:14]) if len(usage_logs) >= 14 else 0

        if previous_revenue == 0:
            return "new" if recent_revenue > 0 else "no_revenue"

        change_percentage = ((recent_revenue - previous_revenue) / previous_revenue) * 100

        if change_percentage > 10:
            return "increasing"
        elif change_percentage < -10:
            return "decreasing"
        else:
            return "stable"

    async def _generate_recommendations(
        self,
        licence: Licence,
        usage_stats: Dict[str, Any],
        revenue_metrics: Dict[str, Any]
    ) -> List[str]:
        """Generate recommendations based on licence usage and performance."""
        recommendations = []

        # Expiry recommendations
        if licence.is_near_expiry:
            recommendations.append("Consider renewing your licence to avoid service interruption")

        # Usage recommendations
        if usage_stats["router_usage_percentage"] > 80:
            recommendations.append("Consider upgrading your licence for more router capacity")

        if usage_stats["user_usage_percentage"] > 80:
            recommendations.append("Consider upgrading your licence for more user capacity")

        # Revenue recommendations
        if revenue_metrics["revenue_trend"] == "increasing":
            recommendations.append("Revenue is growing - consider upgrading to access advanced features")

        # Performance recommendations
        if usage_stats["average_uptime_percentage"] < 95:
            recommendations.append("System uptime is below optimal - check router configurations")

        # Feature recommendations
        if not licence.has_feature("sms_notifications") and revenue_metrics["sms_balance"] == 0:
            recommendations.append("Enable SMS notifications to improve customer communication")

        if not licence.has_feature("advanced_analytics"):
            recommendations.append("Upgrade to access advanced analytics and reporting features")

        return recommendations

    async def monitor_licence_expiry(self) -> Dict[str, Any]:
        """Monitor all licences for expiry and create alerts."""
        try:
            # Get licences expiring in the next 30 days
            expiry_threshold = datetime.utcnow() + timedelta(days=30)
            
            result = await self.db.execute(
                select(Licence).where(
                    and_(
                        Licence.expiry_date <= expiry_threshold,
                        Licence.status == LicenceStatus.ACTIVE
                    )
                )
            )
            expiring_licences = result.scalars().all()

            alerts_created = 0
            for licence in expiring_licences:
                days_remaining = licence.days_until_expiry
                
                # Create appropriate alerts
                if days_remaining <= 0:
                    # Expired
                    await self._create_expiry_alert(licence.id, "expired", "critical")
                    licence.status = LicenceStatus.EXPIRED
                elif days_remaining <= 3:
                    # Critical warning
                    await self._create_expiry_alert(licence.id, "expiry_critical", "critical")
                elif days_remaining <= 7:
                    # High warning
                    await self._create_expiry_alert(licence.id, "expiry_warning", "high")
                elif days_remaining <= 14:
                    # Medium warning
                    await self._create_expiry_alert(licence.id, "expiry_notice", "medium")

                alerts_created += 1

            await self.db.commit()

            return {
                "licences_checked": len(expiring_licences),
                "alerts_created": alerts_created,
                "expired_licences": len([l for l in expiring_licences if l.days_until_expiry <= 0])
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to monitor licence expiry: {e}")
            raise

    async def _create_expiry_alert(
        self,
        licence_id: int,
        alert_type: str,
        severity: str
    ) -> None:
        """Create expiry alert."""
        licence = await self.get_licence_by_id(licence_id)
        if not licence:
            return

        messages = {
            "expired": f"Licence {licence.licence_key} has expired. Renew immediately to continue service.",
            "expiry_critical": f"Licence {licence.licence_key} expires in {licence.days_until_expiry} days. Immediate renewal required.",
            "expiry_warning": f"Licence {licence.licence_key} expires in {licence.days_until_expiry} days. Please renew soon.",
            "expiry_notice": f"Licence {licence.licence_key} expires in {licence.days_until_expiry} days. Consider renewing."
        }

        # Check if similar alert already exists
        result = await self.db.execute(
            select(LicenceAlert).where(
                and_(
                    LicenceAlert.licence_id == licence_id,
                    LicenceAlert.alert_type == alert_type,
                    LicenceAlert.is_active == True
                )
            )
        )
        existing_alert = result.scalar_one_or_none()

        if not existing_alert:
            alert = LicenceAlert(
                licence_id=licence_id,
                alert_type=alert_type,
                severity=severity,
                title=f"Licence {alert_type.replace('_', ' ').title()}",
                message=messages.get(alert_type, "Licence requires attention"),
                action_required="renew_licence" if "expiry" in alert_type else None
            )
            self.db.add(alert)
            await self.db.commit()

    async def get_licence_payments(
        self,
        licence_id: int,
        pagination: PaginationParams,
        status: Optional[LicencePaymentStatus] = None
    ) -> Dict[str, Any]:
        """Get licence payment history."""
        query = select(LicencePayment).where(LicencePayment.licence_id == licence_id)

        if status:
            query = query.where(LicencePayment.status == status)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get payments with pagination
        query = query.order_by(desc(LicencePayment.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        payments = result.scalars().all()

        return {
            "items": payments,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size
        }

    async def create_licence_payment(self, payment_data: Dict[str, Any]) -> LicencePayment:
        """Create a licence payment record."""
        # Generate payment reference
        payment_ref = f"LIC-PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.randbelow(9999):04d}"
        
        payment = LicencePayment(
            payment_reference=payment_ref,
            **payment_data
        )

        self.db.add(payment)
        await self.db.commit()
        await self.db.refresh(payment)
        
        return payment
