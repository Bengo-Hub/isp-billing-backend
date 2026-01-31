"""SMS sending service that integrates SMS providers with the notification system.

This service handles:
- Sending SMS through configured providers (Twilio, Africa's Talking)
- SMS credit tracking and management
- Retry logic for failed SMS
- SMS template rendering
- Bulk SMS sending

The default provider is Twilio. Africa's Talking is recommended for
African markets due to local carrier relationships.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.notification import Notification, NotificationStatus
from app.models.sms_credit import (
    SMSCreditAccount,
    SMSTransaction,
    SMSProviderType,
    SMSTransactionStatus,
    SMSTransactionType,
    SMSGatewayConfig,
    SMSGatewayStatus,
)
from app.integrations.sms import (
    SMSProviderFactory,
    SMSProviderInterface,
    SMSResult,
    SMSDeliveryStatus,
    SMSProviderConfig,
)
from app.integrations.payment_gateways import PaymentGatewayFactory

logger = get_logger(__name__)


class SMSSendingService:
    """Service for sending SMS through configured providers.
    
    Integrates SMS providers with the notification system and handles:
    - Provider selection based on configuration
    - SMS credit tracking
    - Transaction logging
    - Error handling and retries
    
    Usage:
        service = SMSSendingService(db)
        result = await service.send_sms(
            to="+254712345678",
            message="Your subscription expires tomorrow",
            account_id=1,  # SMS credit account
            user_id=1,  # For audit
        )
    """
    
    def __init__(self, db: AsyncSession):
        """Initialize SMS sending service.
        
        Args:
            db: Database session
        """
        self.db = db
        self.logger = get_logger(__name__)
        self._providers: Dict[int, SMSProviderInterface] = {}
    
    async def _get_provider_for_account(
        self,
        account_id: int,
    ) -> Tuple[SMSCreditAccount, SMSProviderInterface]:
        """Get SMS provider for a credit account.
        
        Args:
            account_id: SMS credit account ID
            
        Returns:
            Tuple of (account, provider)
            
        Raises:
            ValueError: If account not found or not configured
        """
        # Check cache first
        if account_id in self._providers:
            result = await self.db.execute(
                select(SMSCreditAccount).where(SMSCreditAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
            if account:
                return account, self._providers[account_id]
        
        # Load account from database
        result = await self.db.execute(
            select(SMSCreditAccount).where(
                and_(
                    SMSCreditAccount.id == account_id,
                    SMSCreditAccount.is_active == True,
                )
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise ValueError(f"SMS credit account {account_id} not found or inactive")
        
        # Create provider based on account configuration
        provider = await self._create_provider(account)
        self._providers[account_id] = provider
        
        return account, provider
    
    async def _get_default_account(self) -> SMSCreditAccount:
        """Get the default SMS credit account.
        
        Returns:
            Default SMS credit account
            
        Raises:
            ValueError: If no default account is configured
        """
        result = await self.db.execute(
            select(SMSCreditAccount).where(
                and_(
                    SMSCreditAccount.is_default == True,
                    SMSCreditAccount.is_active == True,
                )
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            # Fall back to any active account
            result = await self.db.execute(
                select(SMSCreditAccount).where(SMSCreditAccount.is_active == True)
            )
            account = result.scalar_one_or_none()
        
        if not account:
            raise ValueError("No active SMS credit account configured")
        
        return account
    
    async def _create_provider(
        self,
        account: SMSCreditAccount,
    ) -> SMSProviderInterface:
        """Create an SMS provider from account configuration.

        This method prioritizes platform-level SMS gateway credentials
        (configured by Platform Owner) over tenant-specific or environment
        variable credentials. This ensures all ISPs use the Platform Owner's
        SMS gateway (e.g., Africa's Talking) for sending messages.

        Args:
            account: SMS credit account

        Returns:
            Configured SMS provider
        """
        provider_type = account.provider_type

        # First, try to get platform-level SMS gateway credentials
        # Platform gateways have organization_id = NULL
        credentials = await self._get_platform_gateway_credentials(provider_type)

        if credentials:
            self.logger.info(
                f"Using platform-level SMS gateway for provider {provider_type.value}"
            )
        else:
            # Fall back to account-level config or environment variables
            provider_config = account.get_provider_config()
            credentials = {}

            if provider_type == SMSProviderType.TWILIO:
                credentials = {
                    "account_sid": provider_config.get("account_sid") or settings.twilio_account_sid,
                    "auth_token": provider_config.get("auth_token") or settings.twilio_auth_token,
                    "from_number": provider_config.get("from_number") or settings.twilio_phone_number,
                    "messaging_service_sid": provider_config.get("messaging_service_sid"),
                    "status_callback_url": provider_config.get("status_callback_url"),
                }
            elif provider_type == SMSProviderType.AFRICASTALKING:
                credentials = {
                    "username": provider_config.get("username") or settings.africastalking_username,
                    "api_key": provider_config.get("api_key") or settings.africastalking_api_key,
                    "sender_id": provider_config.get("sender_id"),
                    "is_sandbox": provider_config.get("is_sandbox", False),
                }
            else:
                # Try to use provider_config directly
                credentials = provider_config

            self.logger.info(
                f"Using fallback credentials for provider {provider_type.value}"
            )

        return await SMSProviderFactory.create(
            provider_type=provider_type,
            credentials=credentials,
            default_country_code=account.country_code,
        )

    async def _get_platform_gateway_credentials(
        self,
        provider_type: SMSProviderType,
    ) -> Optional[Dict[str, Any]]:
        """Get credentials from platform-level SMS gateway configuration.

        Platform gateways are configured by the Platform Owner and have
        organization_id = NULL. All ISPs use these shared credentials.

        Args:
            provider_type: The SMS provider type to look for

        Returns:
            Decrypted credentials dict, or None if no platform gateway exists
        """
        # Query platform-level gateway (organization_id IS NULL)
        result = await self.db.execute(
            select(SMSGatewayConfig).where(
                and_(
                    SMSGatewayConfig.organization_id.is_(None),
                    SMSGatewayConfig.provider_type == provider_type,
                    SMSGatewayConfig.is_active == True,
                    SMSGatewayConfig.status == SMSGatewayStatus.ACTIVE,
                )
            )
        )
        gateway = result.scalar_one_or_none()

        if not gateway or not gateway.credentials:
            # Try primary gateway if specific provider not found
            result = await self.db.execute(
                select(SMSGatewayConfig).where(
                    and_(
                        SMSGatewayConfig.organization_id.is_(None),
                        SMSGatewayConfig.is_primary == True,
                        SMSGatewayConfig.is_active == True,
                        SMSGatewayConfig.status == SMSGatewayStatus.ACTIVE,
                    )
                )
            )
            gateway = result.scalar_one_or_none()

        if not gateway or not gateway.credentials:
            return None

        # Decrypt credentials using the payment gateway encryption utility
        try:
            encryption_key = getattr(settings, 'encryption_key', None)
            if encryption_key:
                credentials = PaymentGatewayFactory._decrypt_credentials(
                    gateway.credentials, encryption_key
                )
            else:
                # Development mode - try plain JSON
                import json
                credentials = json.loads(gateway.credentials)

            return credentials
        except Exception as e:
            self.logger.error(f"Failed to decrypt platform gateway credentials: {e}")
            return None
    
    async def send_sms(
        self,
        to: str,
        message: str,
        account_id: Optional[int] = None,
        user_id: Optional[int] = None,
        notification_id: Optional[int] = None,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SMSResult:
        """Send a single SMS message.
        
        Args:
            to: Recipient phone number
            message: SMS message content
            account_id: SMS credit account to use (defaults to default account)
            user_id: User ID for audit trail
            notification_id: Associated notification ID
            sender_id: Optional sender ID override
            metadata: Optional metadata
            
        Returns:
            SMSResult with send status
        """
        # Get account and provider
        if account_id:
            account, provider = await self._get_provider_for_account(account_id)
        else:
            account = await self._get_default_account()
            account, provider = await self._get_provider_for_account(account.id)
        
        # Check balance
        if account.current_balance <= 0:
            self.logger.error(f"SMS account {account.account_code} has no credit")
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                message="Insufficient SMS credit",
                error_code="INSUFFICIENT_CREDIT",
            )
        
        # Calculate cost estimate
        segments = provider.calculate_segments(message)
        estimated_cost = Decimal(str(segments)) * account.average_cost_per_sms
        
        if estimated_cost > 0 and account.current_balance < estimated_cost:
            self.logger.warning(
                f"SMS account {account.account_code} may have insufficient credit. "
                f"Balance: {account.current_balance}, Estimated: {estimated_cost}"
            )
        
        # Record balance before send
        balance_before = account.current_balance
        
        # Generate transaction ID
        from app.modules.notifications.sms import SMSCreditService
        credit_service = SMSCreditService(self.db)
        transaction_id = credit_service._generate_transaction_id(SMSTransactionType.USAGE)
        
        # Send SMS
        try:
            result = await provider.send_sms(
                to=to,
                message=message,
                sender_id=sender_id,
                metadata=metadata,
            )
            
            # Determine actual cost
            actual_cost = Decimal(str(result.cost)) if result.cost else estimated_cost
            
            # Create transaction record
            transaction = SMSTransaction(
                transaction_id=transaction_id,
                account_id=account.id,
                transaction_type=SMSTransactionType.USAGE,
                status=SMSTransactionStatus.COMPLETED if result.success else SMSTransactionStatus.FAILED,
                amount=actual_cost,
                currency=result.currency or account.currency,
                recipient_phone=to,
                message_content=message[:500] if message else None,  # Truncate for storage
                message_length=len(message) if message else 0,
                sms_count=result.segments or segments,
                provider_transaction_id=result.message_id,
                provider_response=result.raw_response,
                delivery_status=result.status.value,
                user_id=user_id,
                notification_id=notification_id,
                balance_before=balance_before,
                balance_after=balance_before - actual_cost if result.success else balance_before,
                processed_at=datetime.utcnow(),
                error_message=result.message if not result.success else None,
            )
            
            self.db.add(transaction)
            
            # Update account balance if successful
            if result.success:
                account.update_balance(actual_cost, SMSTransactionType.USAGE)
                account.total_messages_sent += 1
                account.total_amount_spent += actual_cost
                account.last_successful_send = datetime.utcnow()
                account.consecutive_failures = 0
                
                # Update average cost per SMS
                if account.total_messages_sent > 0:
                    account.average_cost_per_sms = (
                        account.total_amount_spent / account.total_messages_sent
                    )
            else:
                account.consecutive_failures += 1
            
            # Update notification status if linked
            if notification_id:
                await self._update_notification_status(
                    notification_id,
                    result.success,
                    result.message_id,
                    result.message,
                )
            
            await self.db.commit()
            
            return result
            
        except Exception as e:
            self.logger.error(f"SMS send error: {e}")
            await self.db.rollback()
            
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                message=str(e),
                error_code="SEND_ERROR",
            )
    
    async def send_bulk_sms(
        self,
        recipients: List[str],
        message: str,
        account_id: Optional[int] = None,
        user_id: Optional[int] = None,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send SMS to multiple recipients.
        
        Args:
            recipients: List of recipient phone numbers
            message: SMS message content
            account_id: SMS credit account to use
            user_id: User ID for audit trail
            sender_id: Optional sender ID override
            metadata: Optional metadata
            
        Returns:
            Dictionary with bulk send results
        """
        # Get account and provider
        if account_id:
            account, provider = await self._get_provider_for_account(account_id)
        else:
            account = await self._get_default_account()
            account, provider = await self._get_provider_for_account(account.id)
        
        # Check balance for bulk
        segments = provider.calculate_segments(message)
        estimated_total = Decimal(str(len(recipients) * segments)) * account.average_cost_per_sms
        
        if account.current_balance < estimated_total:
            self.logger.warning(
                f"SMS account {account.account_code} may have insufficient credit for bulk. "
                f"Balance: {account.current_balance}, Estimated: {estimated_total}"
            )
        
        # Send bulk SMS
        bulk_result = await provider.send_bulk_sms(
            recipients=recipients,
            message=message,
            sender_id=sender_id,
            metadata=metadata,
        )
        
        # Create transaction records
        for result in bulk_result.results:
            actual_cost = Decimal(str(result.cost)) if result.cost else account.average_cost_per_sms
            
            transaction = SMSTransaction(
                transaction_id=f"BULK-{result.message_id}" if result.message_id else f"BULK-{datetime.utcnow().timestamp()}",
                account_id=account.id,
                transaction_type=SMSTransactionType.USAGE,
                status=SMSTransactionStatus.COMPLETED if result.success else SMSTransactionStatus.FAILED,
                amount=actual_cost,
                currency=result.currency or account.currency,
                recipient_phone=result.recipient,
                message_content=message[:500] if message else None,
                message_length=len(message) if message else 0,
                sms_count=result.segments,
                provider_transaction_id=result.message_id,
                delivery_status=result.status.value,
                user_id=user_id,
                balance_before=account.current_balance,
                balance_after=account.current_balance - actual_cost if result.success else account.current_balance,
                processed_at=datetime.utcnow(),
                error_message=result.message if not result.success else None,
            )
            
            self.db.add(transaction)
            
            if result.success:
                account.update_balance(actual_cost, SMSTransactionType.USAGE)
                account.total_messages_sent += 1
        
        # Update account totals
        if bulk_result.total_cost:
            account.total_amount_spent += Decimal(str(bulk_result.total_cost))
        
        if account.total_messages_sent > 0:
            account.average_cost_per_sms = account.total_amount_spent / account.total_messages_sent
        
        account.last_successful_send = datetime.utcnow()
        
        await self.db.commit()
        
        return {
            "total": bulk_result.total,
            "successful": bulk_result.successful,
            "failed": bulk_result.failed,
            "total_cost": float(bulk_result.total_cost) if bulk_result.total_cost else None,
            "currency": bulk_result.currency,
        }
    
    async def _update_notification_status(
        self,
        notification_id: int,
        success: bool,
        external_id: Optional[str],
        error_message: Optional[str],
    ) -> None:
        """Update notification status after SMS send.
        
        Args:
            notification_id: Notification ID
            success: Whether send was successful
            external_id: Provider message ID
            error_message: Error message if failed
        """
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()
        
        if notification:
            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
                notification.external_id = external_id
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = error_message
                notification.retry_count += 1
    
    async def process_delivery_callback(
        self,
        provider_type: SMSProviderType,
        callback_data: Dict[str, Any],
    ) -> Optional[SMSTransaction]:
        """Process SMS delivery callback from provider.
        
        Args:
            provider_type: Provider type
            callback_data: Callback payload from provider
            
        Returns:
            Updated transaction if found
        """
        message_id = None
        status = None
        
        if provider_type == SMSProviderType.TWILIO:
            # Parse Twilio callback
            message_id = callback_data.get("MessageSid")
            status = callback_data.get("MessageStatus", "").lower()
        elif provider_type == SMSProviderType.AFRICASTALKING:
            # Parse Africa's Talking callback
            message_id = callback_data.get("id")
            status = callback_data.get("status", "").lower()
        
        if not message_id:
            self.logger.warning(f"No message ID in callback: {callback_data}")
            return None
        
        # Find transaction
        result = await self.db.execute(
            select(SMSTransaction).where(
                SMSTransaction.provider_transaction_id == message_id
            )
        )
        transaction = result.scalar_one_or_none()
        
        if transaction:
            transaction.delivery_status = status
            transaction.delivery_time = datetime.utcnow()
            await self.db.commit()
            
            # Update linked notification
            if transaction.notification_id and status == "delivered":
                result = await self.db.execute(
                    select(Notification).where(Notification.id == transaction.notification_id)
                )
                notification = result.scalar_one_or_none()
                if notification:
                    notification.status = NotificationStatus.DELIVERED
                    notification.delivered_at = datetime.utcnow()
                    await self.db.commit()
        
        return transaction
    
    async def get_provider_health(
        self,
        account_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Check SMS provider health.
        
        Args:
            account_id: Specific account to check (or default)
            
        Returns:
            Provider health status
        """
        if account_id:
            account, provider = await self._get_provider_for_account(account_id)
        else:
            account = await self._get_default_account()
            account, provider = await self._get_provider_for_account(account.id)
        
        health = await provider.health_check()
        health["account_code"] = account.account_code
        health["account_balance"] = float(account.current_balance)
        health["account_currency"] = account.currency
        
        return health
