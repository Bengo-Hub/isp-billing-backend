"""SMS credit management service with production-ready features."""

import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, ExternalServiceError
from app.models.sms_credit import (
    SMSCreditAccount,
    SMSTransaction,
    SMSTopUp,
    SMSCreditAlert,
    PhoneNumberManagement,
    SMSCreditUsageStats,
    SMSProviderType,
    SMSTransactionStatus,
    SMSTransactionType
)
from app.api.deps import PaginationParams

logger = get_logger(__name__)


class SMSCreditService:
    """Production-ready SMS credit management service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    def _generate_account_code(self, account_name: str) -> str:
        """Generate unique account code."""
        name_part = ''.join(c.upper() for c in account_name if c.isalnum())[:6]
        random_part = ''.join(secrets.choice(string.digits) for _ in range(4))
        return f"SMS-{name_part}-{random_part}"

    def _generate_transaction_id(self, transaction_type: SMSTransactionType) -> str:
        """Generate unique transaction ID."""
        type_prefix = {
            SMSTransactionType.TOP_UP: "TU",
            SMSTransactionType.USAGE: "US",
            SMSTransactionType.REFUND: "RF",
            SMSTransactionType.ADJUSTMENT: "AD",
            SMSTransactionType.BONUS: "BN"
        }
        
        prefix = type_prefix.get(transaction_type, "TX")
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_part = ''.join(secrets.choice(string.digits) for _ in range(4))
        
        return f"{prefix}-{timestamp}-{random_part}"

    async def create_sms_account(
        self,
        account_data: Dict[str, Any],
        created_by: int
    ) -> SMSCreditAccount:
        """Create a new SMS credit account."""
        try:
            # Generate unique account code
            account_code = self._generate_account_code(account_data['account_name'])
            
            while await self._account_code_exists(account_code):
                account_code = self._generate_account_code(account_data['account_name'])

            # Validate and format phone number
            formatted_number = self._format_phone_number(
                account_data['phone_number'],
                account_data.get('country_code', '+254')
            )

            account = SMSCreditAccount(
                account_code=account_code,
                formatted_number=formatted_number,
                created_by=created_by,
                **account_data
            )

            self.db.add(account)
            await self.db.commit()
            await self.db.refresh(account)

            # Create initial usage stats record
            await self._create_initial_usage_stats(account.id)

            self.logger.info(f"Created SMS credit account {account_code}")
            return account

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to create SMS credit account: {e}")
            raise

    async def top_up_sms_credit(
        self,
        account_id: int,
        amount: Decimal,
        payment_method: str,
        requested_by: int,
        sms_credits: Optional[int] = None,
        payment_reference: Optional[str] = None
    ) -> SMSTopUp:
        """Top up SMS credit for an account."""
        account = await self.get_account_by_id(account_id)
        if not account:
            raise ValidationError(f"SMS account {account_id} not found")

        try:
            # Calculate SMS credits if not provided
            if sms_credits is None:
                # Default rate: 1 KES = 1 SMS credit (adjust based on provider)
                sms_credits = int(amount)

            cost_per_sms = amount / sms_credits if sms_credits > 0 else Decimal('0')

            # Generate top-up reference
            top_up_ref = f"TOPUP-{account.account_code}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            top_up = SMSTopUp(
                top_up_reference=top_up_ref,
                account_id=account_id,
                amount=amount,
                currency=account.currency,
                sms_credits=sms_credits,
                cost_per_sms=cost_per_sms,
                payment_method=payment_method,
                payment_reference=payment_reference,
                requested_by=requested_by,
                balance_before=account.current_balance,
                status=SMSTransactionStatus.PENDING
            )

            self.db.add(top_up)
            await self.db.commit()
            await self.db.refresh(top_up)

            self.logger.info(f"Created SMS top-up {top_up_ref} for {amount} {account.currency}")
            return top_up

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to create SMS top-up for account {account_id}: {e}")
            raise

    async def process_top_up(
        self,
        top_up_id: int,
        external_transaction_id: str,
        approved_by: int,
        provider_response: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Process a top-up and update account balance."""
        top_up = await self.db.get(SMSTopUp, top_up_id)
        if not top_up:
            return False

        try:
            account = await self.get_account_by_id(top_up.account_id)
            if not account:
                return False

            # Update top-up status
            top_up.status = SMSTransactionStatus.COMPLETED
            top_up.external_transaction_id = external_transaction_id
            top_up.approved_by = approved_by
            top_up.processed_at = datetime.utcnow()
            top_up.provider_response = provider_response
            top_up.balance_after = account.current_balance + top_up.amount

            # Update account balance
            account.update_balance(top_up.amount, SMSTransactionType.TOP_UP)

            # Create transaction record
            transaction = SMSTransaction(
                transaction_id=self._generate_transaction_id(SMSTransactionType.TOP_UP),
                account_id=account.id,
                transaction_type=SMSTransactionType.TOP_UP,
                status=SMSTransactionStatus.COMPLETED,
                amount=top_up.amount,
                currency=top_up.currency,
                top_up_id=top_up.id,
                balance_before=top_up.balance_before,
                balance_after=top_up.balance_after,
                processed_at=datetime.utcnow()
            )

            self.db.add(transaction)
            await self.db.commit()

            # Clear low balance alerts if balance is now sufficient
            if account.current_balance > account.minimum_balance_threshold:
                await self._clear_low_balance_alerts(account.id)

            self.logger.info(f"Processed SMS top-up {top_up.top_up_reference}")
            return True

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to process top-up {top_up_id}: {e}")
            return False

    async def record_sms_usage(
        self,
        account_id: int,
        recipient_phone: str,
        message_content: str,
        cost: Decimal,
        user_id: Optional[int] = None,
        notification_id: Optional[int] = None,
        provider_transaction_id: Optional[str] = None,
        delivery_status: Optional[str] = None
    ) -> SMSTransaction:
        """Record SMS usage and deduct from balance."""
        account = await self.get_account_by_id(account_id)
        if not account:
            raise ValidationError(f"SMS account {account_id} not found")

        if account.current_balance < cost:
            raise ValidationError("Insufficient SMS credit balance")

        try:
            # Calculate message length and SMS count
            message_length = len(message_content)
            sms_count = max(1, (message_length + 159) // 160)  # 160 chars per SMS

            transaction = SMSTransaction(
                transaction_id=self._generate_transaction_id(SMSTransactionType.USAGE),
                account_id=account_id,
                transaction_type=SMSTransactionType.USAGE,
                status=SMSTransactionStatus.COMPLETED,
                amount=cost,
                currency=account.currency,
                recipient_phone=recipient_phone,
                message_content=message_content,
                message_length=message_length,
                sms_count=sms_count,
                user_id=user_id,
                notification_id=notification_id,
                provider_transaction_id=provider_transaction_id,
                delivery_status=delivery_status,
                balance_before=account.current_balance,
                balance_after=account.current_balance - cost,
                processed_at=datetime.utcnow()
            )

            self.db.add(transaction)

            # Update account balance and statistics
            account.update_balance(cost, SMSTransactionType.USAGE)
            account.total_messages_sent += sms_count
            account.total_amount_spent += cost
            
            # Update average cost per SMS
            if account.total_messages_sent > 0:
                account.average_cost_per_sms = account.total_amount_spent / account.total_messages_sent

            # Update phone number management
            await self._update_phone_number_stats(recipient_phone, delivery_status == "delivered")

            await self.db.commit()
            await self.db.refresh(transaction)

            # Check for low balance and create alert if needed
            if account.is_low_balance:
                await self._create_low_balance_alert(account.id)

            # Trigger auto top-up if enabled
            if account.needs_auto_top_up:
                await self._trigger_auto_top_up(account.id)

            return transaction

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to record SMS usage for account {account_id}: {e}")
            raise

    async def get_account_balance(self, account_id: int) -> Optional[Dict[str, Any]]:
        """Get SMS account balance and status."""
        account = await self.get_account_by_id(account_id)
        if not account:
            return None

        # Get recent transactions
        result = await self.db.execute(
            select(SMSTransaction)
            .where(SMSTransaction.account_id == account_id)
            .order_by(desc(SMSTransaction.created_at))
            .limit(10)
        )
        recent_transactions = result.scalars().all()

        # Get usage stats for today
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.db.execute(
            select(SMSCreditUsageStats)
            .where(
                and_(
                    SMSCreditUsageStats.account_id == account_id,
                    SMSCreditUsageStats.stats_date == today,
                    SMSCreditUsageStats.period_type == "daily"
                )
            )
        )
        today_stats = result.scalar_one_or_none()

        return {
            "account_id": account_id,
            "account_name": account.account_name,
            "current_balance": float(account.current_balance),
            "currency": account.currency,
            "is_low_balance": account.is_low_balance,
            "minimum_threshold": float(account.minimum_balance_threshold),
            "total_messages_sent": account.total_messages_sent,
            "average_cost_per_sms": float(account.average_cost_per_sms),
            "today_usage": {
                "messages_sent": today_stats.messages_sent if today_stats else 0,
                "cost": float(today_stats.total_cost) if today_stats else 0,
                "delivery_rate": float(today_stats.delivery_rate) if today_stats else 0
            },
            "recent_transactions": [
                {
                    "id": tx.id,
                    "type": tx.transaction_type.value,
                    "amount": float(tx.amount),
                    "status": tx.status.value,
                    "created_at": tx.created_at.isoformat()
                }
                for tx in recent_transactions
            ],
            "auto_top_up_enabled": account.auto_top_up_enabled,
            "needs_auto_top_up": account.needs_auto_top_up
        }

    async def get_sms_transaction_history(
        self,
        account_id: int,
        pagination: PaginationParams,
        transaction_type: Optional[SMSTransactionType] = None,
        status: Optional[SMSTransactionStatus] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get SMS transaction history with filtering."""
        query = select(SMSTransaction).where(SMSTransaction.account_id == account_id)

        # Apply filters
        if transaction_type:
            query = query.where(SMSTransaction.transaction_type == transaction_type)
        if status:
            query = query.where(SMSTransaction.status == status)
        if start_date:
            query = query.where(SMSTransaction.created_at >= start_date)
        if end_date:
            query = query.where(SMSTransaction.created_at <= end_date)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get transactions with pagination
        query = query.order_by(desc(SMSTransaction.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        transactions = result.scalars().all()

        return {
            "items": transactions,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size
        }

    async def validate_phone_number(
        self,
        phone_number: str,
        country_code: str = "+254",
        validation_method: str = "sms"
    ) -> Dict[str, Any]:
        """Validate a phone number and add to management system."""
        try:
            # Format phone number
            formatted_number = self._format_phone_number(phone_number, country_code)
            
            # Check if number already exists
            result = await self.db.execute(
                select(PhoneNumberManagement)
                .where(PhoneNumberManagement.formatted_number == formatted_number)
            )
            existing_number = result.scalar_one_or_none()

            if existing_number:
                return {
                    "phone_number": formatted_number,
                    "is_validated": existing_number.is_validated,
                    "validation_required": not existing_number.is_validated,
                    "existing_record": True
                }

            # Create new phone number record
            validation_code = ''.join(secrets.choice(string.digits) for _ in range(6))
            
            phone_record = PhoneNumberManagement(
                phone_number=phone_number,
                country_code=country_code,
                formatted_number=formatted_number,
                validation_method=validation_method,
                validation_code=validation_code,
                number_type=self._detect_number_type(formatted_number),
                carrier=self._detect_carrier(formatted_number),
                region=self._detect_region(country_code)
            )

            self.db.add(phone_record)
            await self.db.commit()
            await self.db.refresh(phone_record)

            # Send validation SMS (if method is SMS)
            if validation_method == "sms":
                await self._send_validation_sms(phone_record, validation_code)

            return {
                "phone_number": formatted_number,
                "is_validated": False,
                "validation_required": True,
                "validation_code_sent": validation_method == "sms",
                "existing_record": False
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to validate phone number {phone_number}: {e}")
            raise

    async def get_sms_usage_analytics(
        self,
        account_id: int,
        period_type: str = "daily",
        days: int = 30
    ) -> Dict[str, Any]:
        """Get SMS usage analytics."""
        account = await self.get_account_by_id(account_id)
        if not account:
            raise ValidationError(f"SMS account {account_id} not found")

        # Calculate date range
        end_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = end_date - timedelta(days=days)

        # Get usage stats for the period
        result = await self.db.execute(
            select(SMSCreditUsageStats)
            .where(
                and_(
                    SMSCreditUsageStats.account_id == account_id,
                    SMSCreditUsageStats.stats_date >= start_date,
                    SMSCreditUsageStats.period_type == period_type
                )
            )
            .order_by(SMSCreditUsageStats.stats_date.asc())
        )
        usage_stats = result.scalars().all()

        # Process analytics data
        analytics_data = []
        total_sent = 0
        total_cost = Decimal('0')
        total_delivered = 0

        for stats in usage_stats:
            analytics_data.append({
                "date": stats.stats_date.isoformat(),
                "messages_sent": stats.messages_sent,
                "messages_delivered": stats.messages_delivered,
                "messages_failed": stats.messages_failed,
                "total_cost": float(stats.total_cost),
                "delivery_rate": float(stats.delivery_rate),
                "breakdown": {
                    "notification": stats.notification_sms,
                    "marketing": stats.marketing_sms,
                    "verification": stats.verification_sms,
                    "alerts": stats.alert_sms
                }
            })
            
            total_sent += stats.messages_sent
            total_cost += stats.total_cost
            total_delivered += stats.messages_delivered

        # Calculate overall metrics
        overall_delivery_rate = (total_delivered / total_sent * 100) if total_sent > 0 else 0
        average_cost_per_sms = total_cost / total_sent if total_sent > 0 else Decimal('0')

        return {
            "account_id": account_id,
            "period_type": period_type,
            "period_days": days,
            "analytics_data": analytics_data,
            "summary": {
                "total_messages_sent": total_sent,
                "total_messages_delivered": total_delivered,
                "total_cost": float(total_cost),
                "overall_delivery_rate": round(overall_delivery_rate, 2),
                "average_cost_per_sms": float(average_cost_per_sms),
                "current_balance": float(account.current_balance)
            }
        }

    async def get_phone_number_management(
        self,
        pagination: PaginationParams,
        search: Optional[str] = None,
        is_validated: Optional[bool] = None,
        is_blacklisted: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Get phone number management records."""
        query = select(PhoneNumberManagement)

        # Apply filters
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    PhoneNumberManagement.phone_number.ilike(search_term),
                    PhoneNumberManagement.formatted_number.ilike(search_term),
                    PhoneNumberManagement.carrier.ilike(search_term)
                )
            )
        if is_validated is not None:
            query = query.where(PhoneNumberManagement.is_validated == is_validated)
        if is_blacklisted is not None:
            query = query.where(PhoneNumberManagement.is_blacklisted == is_blacklisted)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get records with pagination
        query = query.order_by(desc(PhoneNumberManagement.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        phone_numbers = result.scalars().all()

        return {
            "items": phone_numbers,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size
        }

    # Helper methods
    async def get_account_by_id(self, account_id: int) -> Optional[SMSCreditAccount]:
        """Get SMS credit account by ID."""
        return await self.db.get(SMSCreditAccount, account_id)

    async def _account_code_exists(self, account_code: str) -> bool:
        """Check if account code already exists."""
        result = await self.db.execute(
            select(func.count(SMSCreditAccount.id))
            .where(SMSCreditAccount.account_code == account_code)
        )
        return result.scalar() > 0

    def _format_phone_number(self, phone_number: str, country_code: str) -> str:
        """Format phone number to E.164 format."""
        # Remove all non-digit characters
        digits_only = ''.join(c for c in phone_number if c.isdigit())
        
        # Handle Kenya numbers specifically
        if country_code == "+254":
            if digits_only.startswith("254"):
                return f"+{digits_only}"
            elif digits_only.startswith("0"):
                return f"+254{digits_only[1:]}"
            else:
                return f"+254{digits_only}"
        
        # For other countries, prepend country code if not present
        if not digits_only.startswith(country_code.replace("+", "")):
            return f"{country_code}{digits_only}"
        
        return f"+{digits_only}"

    def _detect_number_type(self, formatted_number: str) -> str:
        """Detect phone number type (mobile, landline, etc.)."""
        # Simplified detection - would use external service in production
        if formatted_number.startswith("+2547") or formatted_number.startswith("+2541"):
            return "mobile"
        return "unknown"

    def _detect_carrier(self, formatted_number: str) -> str:
        """Detect phone carrier."""
        # Simplified detection for Kenya - would use external service in production
        if formatted_number.startswith("+25470") or formatted_number.startswith("+25471"):
            return "Safaricom"
        elif formatted_number.startswith("+25472") or formatted_number.startswith("+25473"):
            return "Airtel"
        elif formatted_number.startswith("+25474"):
            return "Telkom"
        return "Unknown"

    def _detect_region(self, country_code: str) -> str:
        """Detect region from country code."""
        region_map = {
            "+254": "Kenya",
            "+255": "Tanzania",
            "+256": "Uganda",
            "+1": "United States",
            "+44": "United Kingdom"
        }
        return region_map.get(country_code, "Unknown")

    async def _create_initial_usage_stats(self, account_id: int) -> None:
        """Create initial usage stats record."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        stats = SMSCreditUsageStats(
            account_id=account_id,
            stats_date=today,
            period_type="daily",
            starting_balance=Decimal('0'),
            ending_balance=Decimal('0'),
            lowest_balance=Decimal('0'),
            highest_balance=Decimal('0')
        )
        
        self.db.add(stats)
        await self.db.commit()

    async def _update_phone_number_stats(self, phone_number: str, delivered: bool) -> None:
        """Update phone number delivery statistics."""
        result = await self.db.execute(
            select(PhoneNumberManagement)
            .where(PhoneNumberManagement.formatted_number == phone_number)
        )
        phone_record = result.scalar_one_or_none()

        if phone_record:
            phone_record.update_delivery_stats(delivered)
            phone_record.total_sms_sent += 1
            await self.db.commit()

    async def _create_low_balance_alert(self, account_id: int) -> None:
        """Create low balance alert."""
        account = await self.get_account_by_id(account_id)
        if not account:
            return

        # Check if alert already exists
        result = await self.db.execute(
            select(SMSCreditAlert).where(
                and_(
                    SMSCreditAlert.account_id == account_id,
                    SMSCreditAlert.alert_type == "low_balance",
                    SMSCreditAlert.is_active == True
                )
            )
        )
        existing_alert = result.scalar_one_or_none()

        if not existing_alert:
            alert = SMSCreditAlert(
                account_id=account_id,
                alert_type="low_balance",
                severity="high",
                title="Low SMS Credit Balance",
                message=f"SMS credit balance is low: {account.current_balance} {account.currency}. Consider topping up.",
                action_required="top_up_credit",
                trigger_balance=account.current_balance
            )
            self.db.add(alert)
            await self.db.commit()

    async def _clear_low_balance_alerts(self, account_id: int) -> None:
        """Clear low balance alerts."""
        result = await self.db.execute(
            select(SMSCreditAlert).where(
                and_(
                    SMSCreditAlert.account_id == account_id,
                    SMSCreditAlert.alert_type == "low_balance",
                    SMSCreditAlert.is_active == True
                )
            )
        )
        alerts = result.scalars().all()

        for alert in alerts:
            alert.is_active = False

        await self.db.commit()

    async def _trigger_auto_top_up(self, account_id: int) -> None:
        """Trigger automatic top-up for account."""
        account = await self.get_account_by_id(account_id)
        if not account or not account.auto_top_up_enabled:
            return

        try:
            # Create auto top-up record
            await self.top_up_sms_credit(
                account_id=account_id,
                amount=account.auto_top_up_amount,
                payment_method="auto_top_up",
                requested_by=account.created_by,  # System user
                sms_credits=int(account.auto_top_up_amount)
            )

            self.logger.info(f"Triggered auto top-up for account {account.account_code}")

        except Exception as e:
            self.logger.error(f"Failed to trigger auto top-up for account {account_id}: {e}")

    async def _send_validation_sms(self, phone_record: PhoneNumberManagement, validation_code: str) -> None:
        """Send validation SMS to phone number."""
        # This would integrate with the actual SMS service
        # For now, just log the action
        self.logger.info(f"Validation SMS sent to {phone_record.formatted_number} with code {validation_code}")
        
        # In production, this would:
        # 1. Use the SMS service to send the validation code
        # 2. Track the SMS transaction
        # 3. Handle delivery status
