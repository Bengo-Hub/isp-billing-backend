"""Billing and payment management service."""

import asyncio
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.models.billing import (
    Invoice,
    InvoiceItem,
    Payment,
    PaymentLog,
    InvoiceStatus,
    PaymentStatus,
    PaymentMethod
)
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.models.payment_gateway import PaymentTransaction
from app.modules.billing.mpesa import MpesaService
from app.api.deps import PaginationParams
from app.core.logging import get_logger
from app.core.exceptions import BillingError, PaymentError, ValidationError
from app.core.datetime_utils import normalize_datetime
from app.core.tenant_middleware import get_current_organization_id

# NOTE (Phase 2/3): the local payment-gateway integration package was removed —
# customer/tenant payment initiation + confirmation are centralized on treasury-api.
# The Paystack helpers below are retained importable but report that direct gateway
# charging is unavailable (callers should initiate payment via treasury-api).
_GATEWAY_RETIRED_MSG = (
    "Direct payment-gateway charging has been retired in isp-billing — "
    "payments are now initiated and confirmed via treasury-api."
)


class BillingService:
    """Billing and payment management service."""

    def __init__(self, db: AsyncSession, organization_id: Optional[int] = None):
        self.db = db
        self.organization_id = organization_id or get_current_organization_id()
        self.mpesa_service = MpesaService(db)
        self.logger = get_logger(__name__)
        self._max_retries = 3
        self._retry_delay = 1  # seconds

    # Validation methods
    def _validate_amount(self, amount: Decimal) -> bool:
        """Validate payment amount."""
        return amount and amount > 0 and amount <= Decimal('999999.99')

    def _validate_phone_number(self, phone_number: str) -> bool:
        """Validate phone number format."""
        if not phone_number:
            return False
        # Remove any non-digit characters
        clean_phone = re.sub(r'\D', '', phone_number)
        # Check if it's a valid Kenyan phone number (10-13 digits)
        return len(clean_phone) >= 10 and len(clean_phone) <= 13

    def _validate_payment_data(self, payment_data: Dict[str, Any]) -> None:
        """Validate payment data."""
        if 'amount' in payment_data:
            if not isinstance(payment_data['amount'], (int, float, Decimal)):
                raise ValidationError("Amount must be a number")
            amount = Decimal(str(payment_data['amount']))
            if not self._validate_amount(amount):
                raise ValidationError("Invalid amount")
        
        if 'phone_number' in payment_data:
            if not self._validate_phone_number(payment_data['phone_number']):
                raise ValidationError("Invalid phone number format")
        
        if 'payment_method' in payment_data:
            if payment_data['payment_method'] not in [method.value for method in PaymentMethod]:
                raise ValidationError("Invalid payment method")

    async def _retry_operation(self, operation, *args, **kwargs):
        """Retry operation with exponential backoff."""
        for attempt in range(self._max_retries):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                if attempt == self._max_retries - 1:
                    raise e
                self.logger.warning(f"Operation failed (attempt {attempt + 1}/{self._max_retries}): {e}")
                await asyncio.sleep(self._retry_delay * (2 ** attempt))
        return None

    async def get_invoice_by_id(self, invoice_id: int) -> Optional[Invoice]:
        """Get invoice by ID with production-ready error handling."""
        try:
            if not isinstance(invoice_id, int) or invoice_id <= 0:
                raise ValidationError("Invalid invoice ID")
            
            invoice = await self.db.get(Invoice, invoice_id)
            if invoice:
                self.logger.debug(f"Retrieved invoice {invoice_id} for user {invoice.user_id}")
            return invoice
        except SQLAlchemyError as e:
            self.logger.error(f"Database error retrieving invoice {invoice_id}: {e}")
            raise BillingError(f"Failed to retrieve invoice: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error retrieving invoice {invoice_id}: {e}")
            raise BillingError(f"Unexpected error: {e}")

    async def get_invoices(
        self,
        pagination: PaginationParams,
        user_id: Optional[int] = None,
        status: Optional[InvoiceStatus] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all invoices with pagination and filters."""
        query = select(Invoice)

        # Enforce tenant isolation
        if self.organization_id:
            query = query.where(Invoice.organization_id == self.organization_id)

        # Apply filters
        if user_id:
            query = query.where(Invoice.user_id == user_id)
        if status:
            query = query.where(Invoice.status == status)
        if search:
            search_term = f"%{search}%"
            query = query.where(Invoice.invoice_number.ilike(search_term))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get invoices with pagination
        query = query.order_by(Invoice.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        invoices = result.scalars().all()

        return {
            "invoices": invoices,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_invoice(
        self,
        user_id: int,
        subtotal: Decimal,
        subscription_id: Optional[int] = None,
        tax_amount: Decimal = Decimal('0'),
        discount_amount: Decimal = Decimal('0'),
        billing_period_start: Optional[datetime] = None,
        billing_period_end: Optional[datetime] = None,
        notes: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
    ) -> Invoice:
        """Create a new invoice."""
        # Validate that user exists
        user = await self.db.get(User, user_id)
        if not user:
            raise ValidationError(f"User with ID {user_id} does not exist")
        
        # If subscription_id is provided, validate it exists and belongs to the user
        if subscription_id:
            subscription = await self.db.get(Subscription, subscription_id)
            if not subscription:
                raise ValidationError(f"Subscription with ID {subscription_id} does not exist")
            if subscription.user_id != user_id:
                raise ValidationError(f"Subscription {subscription_id} does not belong to user {user_id}")
        
        # Generate invoice number
        invoice_number = await self._generate_invoice_number()
        
        # Calculate total
        total_amount = subtotal + tax_amount - discount_amount
        balance = total_amount

        invoice = Invoice(
            user_id=user_id,
            subscription_id=subscription_id,
            invoice_number=invoice_number,
            subtotal=subtotal,
            tax_amount=tax_amount,
            discount_amount=discount_amount,
            total_amount=total_amount,
            balance=balance,
            issue_date=datetime.utcnow(),
            due_date=datetime.utcnow() + timedelta(days=30),  # 30 days from now
            billing_period_start=normalize_datetime(billing_period_start),
            billing_period_end=normalize_datetime(billing_period_end),
            notes=notes,
            status=InvoiceStatus.DRAFT,
        )

        self.db.add(invoice)
        await self.db.commit()
        await self.db.refresh(invoice)

        # Add invoice items if provided
        if items:
            for item in items:
                await self.add_invoice_item(
                    invoice.id,
                    item.get("description", ""),
                    item.get("quantity", 1),
                    item.get("unit_price", 0),
                    item.get("item_type", "subscription")
                )

        return invoice

    async def add_invoice_item(
        self,
        invoice_id: int,
        description: str,
        quantity: Decimal,
        unit_price: Decimal,
        item_type: str = "subscription",
    ) -> InvoiceItem:
        """Add item to invoice."""
        total_price = quantity * unit_price
        
        item = InvoiceItem(
            invoice_id=invoice_id,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
            item_type=item_type,
        )

        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)

        # Update invoice totals
        await self._update_invoice_totals(invoice_id)

        return item

    async def update_invoice_status(
        self, 
        invoice_id: int, 
        status: InvoiceStatus
    ) -> Optional[Invoice]:
        """Update invoice status."""
        invoice = await self.get_invoice_by_id(invoice_id)
        if not invoice:
            return None

        invoice.status = status
        
        if status == InvoiceStatus.PAID:
            invoice.paid_date = datetime.utcnow()
            invoice.balance = Decimal('0')
        elif status == InvoiceStatus.OVERDUE:
            # Check if due date has passed
            if invoice.due_date < datetime.utcnow():
                invoice.status = InvoiceStatus.OVERDUE

        await self.db.commit()
        await self.db.refresh(invoice)
        return invoice

    async def generate_subscription_invoice(
        self, 
        subscription_id: int
    ) -> Optional[Invoice]:
        """Generate invoice for subscription."""
        subscription = await self.db.get(Subscription, subscription_id)
        if not subscription:
            self.logger.warning(f"Subscription {subscription_id} not found")
            return None

        # Validate that the user still exists
        user = await self.db.get(User, subscription.user_id)
        if not user:
            self.logger.warning(f"User {subscription.user_id} for subscription {subscription_id} not found. Skipping invoice generation.")
            return None

        # Get plan details
        plan = await self.db.get(subscription.plan_id, subscription.plan_id)
        if not plan:
            self.logger.warning(f"Plan {subscription.plan_id} for subscription {subscription_id} not found")
            return None

        # Calculate billing period
        billing_period_start = normalize_datetime(subscription.start_date)
        billing_period_end = normalize_datetime(subscription.end_date)

        # Create invoice
        invoice = await self.create_invoice(
            user_id=subscription.user_id,
            subscription_id=subscription_id,
            subtotal=plan.price,
            billing_period_start=billing_period_start,
            billing_period_end=billing_period_end,
            notes=f"Subscription invoice for {plan.name}",
            items=[{
                "description": f"{plan.name} - {plan.billing_cycle.value}",
                "quantity": 1,
                "unit_price": plan.price,
                "item_type": "subscription"
            }]
        )

        return invoice

    async def generate_billing_cycle_invoices(self) -> Dict[str, Any]:
        """Generate invoices for all active subscriptions."""
        # Get all active subscriptions that need billing
        filters = [
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.is_auto_renewal == True,
        ]
        if self.organization_id:
            filters.append(Subscription.organization_id == self.organization_id)
        result = await self.db.execute(
            select(Subscription).where(and_(*filters))
        )
        subscriptions = result.scalars().all()

        invoices_created = 0
        errors = []

        for subscription in subscriptions:
            try:
                # Check if invoice already exists for this billing period
                existing_invoice = await self.db.execute(
                    select(Invoice).where(
                        and_(
                            Invoice.subscription_id == subscription.id,
                            Invoice.status.in_([
                                InvoiceStatus.DRAFT,
                                InvoiceStatus.PENDING,
                                InvoiceStatus.PAID
                            ])
                        )
                    )
                )
                
                if not existing_invoice.scalar_one_or_none():
                    await self.generate_subscription_invoice(subscription.id)
                    invoices_created += 1
            except Exception as e:
                errors.append(f"Subscription {subscription.id}: {str(e)}")

        return {
            "invoices_created": invoices_created,
            "total_subscriptions": len(subscriptions),
            "errors": errors,
        }

    async def get_payment_by_id(self, payment_id: int) -> Optional[Payment]:
        """Get payment by ID."""
        return await self.db.get(Payment, payment_id)

    async def get_payments(
        self,
        pagination: PaginationParams,
        user_id: Optional[int] = None,
        invoice_id: Optional[int] = None,
        status: Optional[PaymentStatus] = None,
    ) -> Dict[str, Any]:
        """Get all payments with pagination and filters."""
        query = select(Payment)

        # Enforce tenant isolation
        if self.organization_id:
            query = query.where(Payment.organization_id == self.organization_id)

        # Apply filters
        if user_id:
            query = query.where(Payment.user_id == user_id)
        if invoice_id:
            query = query.where(Payment.invoice_id == invoice_id)
        if status:
            query = query.where(Payment.status == status)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get payments with pagination
        query = query.order_by(Payment.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        payments = result.scalars().all()

        return {
            "payments": payments,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_payment(
        self,
        user_id: int,
        amount: Decimal,
        payment_method: PaymentMethod,
        invoice_id: Optional[int] = None,
        transaction_id: Optional[str] = None,
        reference_number: Optional[str] = None,
        notes: Optional[str] = None,
        is_manual: bool = False,
    ) -> Payment:
        """Create a new payment.

        ``is_manual`` marks an admin-recorded reconciliation (e.g. the "Record
        Payment" action) where the funds were already received out-of-band. Such
        payments are immediately COMPLETED and applied to the invoice regardless
        of method (cash, bank transfer, manually-received M-PESA, etc.).
        """
        # Generate payment number
        payment_number = await self._generate_payment_number()

        # Offline methods (cash / bank transfer) are recorded by an admin AFTER
        # the funds were physically received, so they are immediately COMPLETED
        # and reconciled. Online methods (M-PESA / card) stay PENDING until the
        # gateway callback confirms them — UNLESS this is an explicit manual
        # reconciliation, in which case the admin is asserting receipt.
        offline_methods = {PaymentMethod.CASH, PaymentMethod.BANK_TRANSFER}
        is_offline = is_manual or payment_method in offline_methods

        payment = Payment(
            user_id=user_id,
            invoice_id=invoice_id,
            payment_number=payment_number,
            amount=amount,
            payment_method=payment_method,
            transaction_id=transaction_id,
            reference_number=reference_number,
            notes=notes,
            status=PaymentStatus.COMPLETED if is_offline else PaymentStatus.PENDING,
            is_manual_payment=is_offline,
            payment_date=datetime.utcnow(),
            processed_date=datetime.utcnow() if is_offline else None,
        )

        self.db.add(payment)
        await self.db.commit()
        await self.db.refresh(payment)

        # Reconcile offline payments immediately: apply to the invoice, which
        # marks it paid and activates + router-syncs the linked subscription.
        if is_offline and invoice_id:
            await self._apply_payment_to_invoice(invoice_id, amount)
            await self.db.refresh(payment)

        return payment

    async def process_mpesa_payment(
        self,
        user_id: int,
        phone_number: str,
        amount: int,
        invoice_number: str,
        description: str = "Payment for internet service",
    ) -> Dict[str, Any]:
        """Process MPESA STK Push payment."""
        try:
            # Initiate MPESA payment
            result = await self.mpesa_service.initiate_payment(
                phone_number=phone_number,
                amount=amount,
                invoice_number=invoice_number,
                description=description
            )

            if result.get("success"):
                # Create payment record
                payment = await self.create_payment(
                    user_id=user_id,
                    amount=Decimal(str(amount)),
                    payment_method=PaymentMethod.MPESA,
                    transaction_id=result.get("merchant_request_id"),
                    reference_number=result.get("checkout_request_id"),
                    notes=f"MPESA STK Push for invoice {invoice_number}",
                )

                return {
                    "success": True,
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "merchant_request_id": result.get("merchant_request_id"),
                    "checkout_request_id": result.get("checkout_request_id"),
                    "customer_message": result.get("customer_message"),
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Payment initiation failed"),
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def handle_mpesa_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MPESA payment callback."""
        try:
            result = await self.mpesa_service.handle_payment_callback(callback_data)

            if result.get("success") and result.get("payment_successful"):
                # Find payment by checkout request ID
                checkout_request_id = result.get("checkout_request_id")
                if checkout_request_id:
                    payment = await self.db.execute(
                        select(Payment).where(Payment.reference_number == checkout_request_id)
                    )
                    payment = payment.scalar_one_or_none()

                    if payment:
                        # Update payment status
                        payment.status = PaymentStatus.COMPLETED
                        payment.mpesa_receipt_number = result.get("mpesa_receipt_number")
                        payment.mpesa_phone_number = result.get("phone_number")
                        payment.mpesa_transaction_date = datetime.utcnow()
                        payment.payment_date = datetime.utcnow()
                        payment.processed_date = datetime.utcnow()

                        await self.db.commit()

                        # Update invoice if linked
                        if payment.invoice_id:
                            await self._apply_payment_to_invoice(payment.invoice_id, payment.amount)

                        return {
                            "success": True,
                            "payment_id": payment.id,
                            "message": "Payment processed successfully",
                        }

            return {
                "success": False,
                "error": "Payment processing failed",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    # ==================== PAYSTACK PAYMENT METHODS ====================

    async def initiate_paystack_payment(
        self,
        invoice_id: int,
        callback_url: str,
        user_email: Optional[str] = None,
        user_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a Paystack payment for an invoice.

        Args:
            invoice_id: ID of the invoice to pay
            callback_url: URL to redirect after payment
            user_email: Customer email (required for Paystack)
            user_phone: Customer phone number

        Returns:
            Dict with checkout_url, reference, and status
        """
        # Retired: direct Paystack charging now routes through treasury-api.
        self.logger.warning(
            "initiate_paystack_payment called but local gateway charging is retired "
            f"(invoice={invoice_id}); route via treasury-api."
        )
        return {"success": False, "error": _GATEWAY_RETIRED_MSG}

    async def verify_paystack_payment(self, reference: str) -> Dict[str, Any]:
        """
        Verify a Paystack payment by reference.

        Args:
            reference: Transaction reference

        Returns:
            Dict with verification status and details
        """
        # Retired: payment verification is owned by treasury-api.
        self.logger.warning(
            f"verify_paystack_payment called but local gateway verification is retired "
            f"(ref={reference}); treasury-api is the source of truth."
        )
        return {"success": False, "status": "error", "message": _GATEWAY_RETIRED_MSG}

    async def handle_paystack_webhook(
        self,
        event: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a Paystack webhook event.

        Args:
            event: Webhook event type (e.g., "charge.success")
            data: Webhook payload data

        Returns:
            Dict with processing result
        """
        try:
            reference = data.get("reference", "")

            if not reference:
                return {"success": False, "message": "No reference in webhook data"}

            # Get transaction
            tx_result = await self.db.execute(
                select(PaymentTransaction).where(
                    PaymentTransaction.transaction_reference == reference
                )
            )
            transaction = tx_result.scalar_one_or_none()

            if not transaction:
                self.logger.warning(f"Webhook: Transaction not found for reference {reference}")
                return {"success": False, "message": "Transaction not found"}

            # Store raw callback data
            transaction.callback_data = {"event": event, "data": data}

            if event == "charge.success":
                amount = Decimal(str(data.get("amount", 0))) / 100
                paid_at = None
                if data.get("paid_at"):
                    paid_at = datetime.fromisoformat(data["paid_at"].replace("Z", "+00:00"))

                await self._process_paystack_success(transaction, amount, paid_at)

                return {"success": True, "message": "Payment processed successfully"}

            elif event == "charge.failed":
                transaction.status = "failed"
                transaction.status_message = data.get("gateway_response", "Payment failed")
                await self.db.commit()

                return {"success": True, "message": "Payment failure recorded"}

            elif event in ("transfer.success", "transfer.failed"):
                transaction.status = "completed" if event == "transfer.success" else "failed"
                transaction.completed_at = datetime.utcnow() if event == "transfer.success" else None
                transaction.status_message = data.get("reason", "") if event == "transfer.failed" else None
                await self.db.commit()

                return {"success": True, "message": f"Transfer {event.split('.')[1]} recorded"}

            else:
                self.logger.info(f"Unhandled webhook event: {event}")
                return {"success": True, "message": f"Event {event} acknowledged"}

        except Exception as e:
            self.logger.error(f"Paystack webhook processing error: {e}")
            return {"success": False, "message": str(e)}

    async def _process_paystack_success(
        self,
        transaction: PaymentTransaction,
        amount: Decimal,
        paid_at: Optional[datetime] = None,
    ) -> None:
        """Process a successful Paystack payment."""
        try:
            # Strip timezone info (DB uses TIMESTAMP WITHOUT TIME ZONE)
            if paid_at and hasattr(paid_at, 'tzinfo') and paid_at.tzinfo is not None:
                paid_at = paid_at.replace(tzinfo=None)

            # Update transaction
            transaction.status = "completed"
            transaction.completed_at = paid_at or datetime.utcnow()
            transaction.processed_at = datetime.utcnow()

            # Calculate fees (Paystack Kenya: 1.5% + 100 KES capped at 2000 KES)
            fee = min(amount * Decimal("0.015") + Decimal("100"), Decimal("2000"))
            transaction.gateway_fee = fee
            transaction.net_amount = amount - fee

            # Create payment record
            payment_number = await self._generate_payment_number()
            payment = Payment(
                payment_number=payment_number,
                user_id=transaction.user_id,
                invoice_id=transaction.invoice_id,
                amount=amount,
                currency=transaction.currency,
                payment_method=PaymentMethod.CARD,
                status=PaymentStatus.COMPLETED,
                reference_number=transaction.transaction_reference,
                payment_date=paid_at or datetime.utcnow(),
            )
            self.db.add(payment)

            # Update invoice if linked
            if transaction.invoice_id:
                await self._apply_payment_to_invoice(transaction.invoice_id, amount)

                # Check for WhatsApp subscription invoices and activate
                await self._activate_whatsapp_subscription_if_applicable(transaction.invoice_id)

            # Activate subscription if linked
            if transaction.subscription_id:
                await self._activate_subscription_on_payment(transaction.subscription_id)

            await self.db.commit()

            self.logger.info(
                f"Paystack payment processed: ref={transaction.transaction_reference}, "
                f"amount={amount}, invoice={transaction.invoice_id}"
            )

        except Exception as e:
            self.logger.error(f"Error processing Paystack payment: {e}")
            await self.db.rollback()
            raise

    async def _activate_subscription_on_payment(self, subscription_id: int) -> None:
        """Activate a subscription after successful payment."""
        try:
            subscription = await self.db.get(Subscription, subscription_id)
            if not subscription:
                return

            if subscription.status == SubscriptionStatus.ACTIVE:
                return  # Already active

            # Update subscription status
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.is_router_synced = False  # Mark for sync

            await self.db.commit()

            # Trigger router sync
            try:
                from app.modules.subscriptions.router_sync import SubscriptionRouterSyncService
                sync_service = SubscriptionRouterSyncService(self.db)
                sync_result = await sync_service.sync_subscription_to_router(subscription)

                if sync_result["success"]:
                    self.logger.info(f"Subscription {subscription_id} activated and synced to router")
                else:
                    self.logger.warning(
                        f"Subscription {subscription_id} activated but router sync failed: "
                        f"{sync_result.get('error')}"
                    )
            except Exception as e:
                self.logger.error(f"Router sync error for subscription {subscription_id}: {e}")

        except Exception as e:
            self.logger.error(f"Error activating subscription {subscription_id}: {e}")

    async def _activate_whatsapp_subscription_if_applicable(self, invoice_id: int) -> None:
        """
        Check if a paid invoice is for a WhatsApp subscription and activate it.

        Uses the invoice notes field (format: 'whatsapp_subscription:{provider}')
        or invoice item type to identify WhatsApp subscription invoices.
        """
        try:
            invoice = await self.db.get(Invoice, invoice_id)
            if not invoice:
                return

            # Check invoice notes for WhatsApp subscription marker
            is_whatsapp = False
            provider = "APIWAP"

            if invoice.notes and invoice.notes.startswith("whatsapp_subscription:"):
                is_whatsapp = True
                provider = invoice.notes.split(":", 1)[1] if ":" in invoice.notes else "APIWAP"

            if not is_whatsapp:
                # Also check invoice items for whatsapp_subscription type
                from app.models.billing import InvoiceItem
                item_result = await self.db.execute(
                    select(InvoiceItem).where(
                        InvoiceItem.invoice_id == invoice_id,
                        InvoiceItem.item_type == "whatsapp_subscription",
                    ).limit(1)
                )
                if item_result.scalar_one_or_none():
                    is_whatsapp = True

            if not is_whatsapp or not invoice.organization_id:
                return

            # Activate or extend WhatsApp subscription for the organization
            from app.models.whatsapp import (
                WhatsAppOrganizationSubscription,
                WhatsAppSubscriptionPackage,
                WhatsAppSubscriptionStatus,
                WhatsAppSubscriptionPayment,
                WhatsAppTransactionStatus,
            )
            from datetime import timedelta

            # Find existing subscription
            sub_result = await self.db.execute(
                select(WhatsAppOrganizationSubscription).where(
                    WhatsAppOrganizationSubscription.organization_id == invoice.organization_id
                )
            )
            subscription = sub_result.scalar_one_or_none()

            # Get package for duration info
            pkg_result = await self.db.execute(
                select(WhatsAppSubscriptionPackage).where(
                    WhatsAppSubscriptionPackage.is_active == True,
                ).limit(1)
            )
            package = pkg_result.scalar_one_or_none()
            extension_days = 30  # Default monthly

            now = datetime.utcnow()

            if subscription:
                # Extend existing subscription
                if subscription.status == WhatsAppSubscriptionStatus.ACTIVE and subscription.end_date > now:
                    subscription.end_date = subscription.end_date + timedelta(days=extension_days)
                else:
                    subscription.start_date = now
                    subscription.end_date = now + timedelta(days=extension_days)
                    subscription.status = WhatsAppSubscriptionStatus.ACTIVE
                    subscription.activated_at = now

                subscription.next_billing_date = subscription.end_date
                subscription.is_trial = False
            else:
                # Create new subscription
                if not package:
                    self.logger.error(f"No WhatsApp subscription package found for org {invoice.organization_id}")
                    return

                subscription = WhatsAppOrganizationSubscription(
                    organization_id=invoice.organization_id,
                    package_id=package.id,
                    status=WhatsAppSubscriptionStatus.ACTIVE,
                    provider_type=package.provider_type,
                    start_date=now,
                    end_date=now + timedelta(days=extension_days),
                    next_billing_date=now + timedelta(days=extension_days),
                    is_trial=False,
                    activated_at=now,
                )
                self.db.add(subscription)
                await self.db.flush()

            # Record WhatsApp subscription payment
            payment_record = WhatsAppSubscriptionPayment(
                subscription_id=subscription.id,
                organization_id=invoice.organization_id,
                payment_reference=invoice.invoice_number,
                amount=invoice.total_amount,
                currency=invoice.currency,
                status=WhatsAppTransactionStatus.COMPLETED,
                paid_at=now,
            )
            self.db.add(payment_record)

            self.logger.info(
                f"WhatsApp subscription activated for org {invoice.organization_id} "
                f"until {subscription.end_date}"
            )

        except Exception as e:
            self.logger.error(f"Error activating WhatsApp subscription for invoice {invoice_id}: {e}")

    async def _generate_paystack_reference(self, prefix: str = "PAY") -> str:
        """Generate unique Paystack transaction reference."""
        import secrets
        import string
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_part = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        return f"{prefix}-{timestamp}-{random_part}"

    async def _apply_payment_to_invoice(self, invoice_id: int, amount: Decimal) -> None:
        """Apply payment to invoice.

        When the invoice becomes fully paid and is linked to a subscription,
        activate that subscription (and sync it to the router). This makes the
        activation behaviour identical across ALL payment paths — M-PESA,
        Paystack, and manual/cash reconciliation — instead of only the gateway
        webhooks. Activation is idempotent (no-op if already ACTIVE).
        """
        invoice = await self.get_invoice_by_id(invoice_id)
        if not invoice:
            return

        # Update invoice payment
        invoice.paid_amount += amount
        invoice.balance = invoice.total_amount - invoice.paid_amount

        # Update status if fully paid
        fully_paid = invoice.balance <= 0
        if fully_paid:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_date = datetime.utcnow()

        await self.db.commit()

        # Activate the linked subscription once the invoice is fully settled.
        if fully_paid and getattr(invoice, "subscription_id", None):
            await self._activate_subscription_on_payment(invoice.subscription_id)

    async def get_user_payment_history(
        self, 
        user_id: int, 
        limit: int = 50
    ) -> List[Payment]:
        """Get payment history for user."""
        result = await self.db.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_overdue_invoices(self) -> List[Invoice]:
        """Get all overdue invoices."""
        now = datetime.utcnow()
        filters = [Invoice.status == InvoiceStatus.PENDING, Invoice.due_date < now]
        if self.organization_id:
            filters.append(Invoice.organization_id == self.organization_id)
        result = await self.db.execute(
            select(Invoice).where(and_(*filters))
        )
        return result.scalars().all()

    async def get_billing_stats(self) -> Dict[str, Any]:
        """Get billing statistics."""
        org_filter = []
        if self.organization_id:
            org_filter.append(Invoice.organization_id == self.organization_id)

        # Total invoices
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(and_(True, *org_filter))
        )
        total_invoices = result.scalar() or 0

        # Paid invoices
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(
                and_(Invoice.status == InvoiceStatus.PAID, *org_filter)
            )
        )
        paid_invoices = result.scalar() or 0

        # Pending invoices
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(
                and_(Invoice.status == InvoiceStatus.PENDING, *org_filter)
            )
        )
        pending_invoices = result.scalar() or 0

        # Overdue invoices
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(
                and_(Invoice.status == InvoiceStatus.OVERDUE, *org_filter)
            )
        )
        overdue_invoices = result.scalar() or 0

        # Total revenue
        result = await self.db.execute(
            select(func.sum(Invoice.paid_amount)).where(
                and_(Invoice.status == InvoiceStatus.PAID, *org_filter)
            )
        )
        total_revenue = result.scalar() or 0

        # Pending revenue
        result = await self.db.execute(
            select(func.sum(Invoice.total_amount)).where(
                and_(Invoice.status.in_([InvoiceStatus.PENDING, InvoiceStatus.OVERDUE]), *org_filter)
            )
        )
        pending_revenue = result.scalar() or 0

        return {
            "total_invoices": total_invoices,
            "paid_invoices": paid_invoices,
            "pending_invoices": pending_invoices,
            "overdue_invoices": overdue_invoices,
            "total_revenue": float(total_revenue),
            "pending_revenue": float(pending_revenue),
            "collection_rate": (paid_invoices / total_invoices * 100) if total_invoices > 0 else 0,
        }

    async def _generate_invoice_number(self) -> str:
        """Generate unique invoice number."""
        # Get current year and month
        now = datetime.utcnow()
        year_month = now.strftime("%Y%m")
        
        # Get count of invoices for this month
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.invoice_number.like(f"INV-{year_month}%")
            )
        )
        count = result.scalar() or 0
        
        # Generate invoice number
        invoice_number = f"INV-{year_month}-{count + 1:04d}"
        return invoice_number

    async def _generate_payment_number(self) -> str:
        """Generate unique payment number."""
        # Get current year and month
        now = datetime.utcnow()
        year_month = now.strftime("%Y%m")
        
        # Get count of payments for this month
        result = await self.db.execute(
            select(func.count(Payment.id)).where(
                Payment.payment_number.like(f"PAY-{year_month}%")
            )
        )
        count = result.scalar() or 0
        
        # Generate payment number
        payment_number = f"PAY-{year_month}-{count + 1:04d}"
        return payment_number

    async def _update_invoice_totals(self, invoice_id: int) -> None:
        """Update invoice totals based on items."""
        # Get all items for invoice
        result = await self.db.execute(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
        )
        items = result.scalars().all()

        # Calculate totals
        subtotal = sum(item.total_price for item in items)
        
        # Get invoice
        invoice = await self.get_invoice_by_id(invoice_id)
        if invoice:
            invoice.subtotal = subtotal
            invoice.total_amount = subtotal + invoice.tax_amount - invoice.discount_amount
            invoice.balance = invoice.total_amount - invoice.paid_amount
            
            await self.db.commit()
    
    async def update_invoice_item(self, item_id: int, update_data: Dict[str, Any]) -> Optional[InvoiceItem]:
        """Update invoice item."""
        try:
            if not isinstance(item_id, int) or item_id <= 0:
                raise ValidationError("Invalid item ID")
            
            result = await self.db.execute(
                select(InvoiceItem).where(InvoiceItem.id == item_id)
            )
            item = result.scalar_one_or_none()
            
            if not item:
                return None
            
            # Update fields
            for field, value in update_data.items():
                if hasattr(item, field) and value is not None:
                    setattr(item, field, value)
            
            await self.db.commit()
            await self.db.refresh(item)
            
            self.logger.info(f"Updated invoice item {item_id}")
            return item
            
        except ValidationError:
            await self.db.rollback()
            raise
        except SQLAlchemyError as e:
            await self.db.rollback()
            self.logger.error(f"Database error updating invoice item {item_id}: {e}")
            raise BillingError(f"Failed to update invoice item: {e}")
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Unexpected error updating invoice item {item_id}: {e}")
            raise BillingError(f"Unexpected error: {e}")
    
    async def delete_invoice_item(self, item_id: int) -> bool:
        """Delete invoice item."""
        try:
            if not isinstance(item_id, int) or item_id <= 0:
                raise ValidationError("Invalid item ID")
            
            result = await self.db.execute(
                select(InvoiceItem).where(InvoiceItem.id == item_id)
            )
            item = result.scalar_one_or_none()
            
            if not item:
                return False
            
            await self.db.delete(item)
            await self.db.commit()
            
            self.logger.info(f"Deleted invoice item {item_id}")
            return True
            
        except ValidationError:
            await self.db.rollback()
            raise
        except SQLAlchemyError as e:
            await self.db.rollback()
            self.logger.error(f"Database error deleting invoice item {item_id}: {e}")
            raise BillingError(f"Failed to delete invoice item: {e}")
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Unexpected error deleting invoice item {item_id}: {e}")
            raise BillingError(f"Unexpected error: {e}")
    
    async def get_payment_statistics(self) -> Dict[str, Any]:
        """Get payment statistics."""
        try:
            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=7)
            month_start = today_start - timedelta(days=30)

            org_filter = []
            if self.organization_id:
                org_filter.append(Payment.organization_id == self.organization_id)

            # Get total payments count
            total_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(and_(True, *org_filter))
            )
            total_payments = total_payments_result.scalar() or 0

            # Get successful payments count
            successful_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(
                    and_(Payment.status == PaymentStatus.COMPLETED, *org_filter)
                )
            )
            successful_payments = successful_payments_result.scalar() or 0

            # Get failed payments count
            failed_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(
                    and_(Payment.status == PaymentStatus.FAILED, *org_filter)
                )
            )
            failed_payments = failed_payments_result.scalar() or 0

            # Get pending payments count
            pending_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(
                    and_(Payment.status == PaymentStatus.PENDING, *org_filter)
                )
            )
            pending_payments = pending_payments_result.scalar() or 0

            # Get total amount collected
            total_amount_result = await self.db.execute(
                select(func.sum(Payment.amount)).where(
                    and_(Payment.status == PaymentStatus.COMPLETED, *org_filter)
                )
            )
            total_amount = total_amount_result.scalar() or 0

            # Get payment counts by method
            mpesa_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(
                    and_(Payment.payment_method == PaymentMethod.MPESA, Payment.status == PaymentStatus.COMPLETED, *org_filter)
                )
            )
            mpesa_payments = mpesa_payments_result.scalar() or 0

            cash_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(
                    and_(Payment.payment_method == PaymentMethod.CASH, Payment.status == PaymentStatus.COMPLETED, *org_filter)
                )
            )
            cash_payments = cash_payments_result.scalar() or 0

            bank_transfer_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(
                    and_(Payment.payment_method == PaymentMethod.BANK_TRANSFER, Payment.status == PaymentStatus.COMPLETED, *org_filter)
                )
            )
            bank_transfer_payments = bank_transfer_payments_result.scalar() or 0

            # Calculate daily earnings (today)
            daily_earnings_result = await self.db.execute(
                select(func.sum(Payment.amount)).where(
                    and_(
                        Payment.status == PaymentStatus.COMPLETED,
                        Payment.created_at >= today_start,
                        *org_filter,
                    )
                )
            )
            daily_earnings = daily_earnings_result.scalar() or 0

            # Calculate weekly earnings (last 7 days)
            weekly_earnings_result = await self.db.execute(
                select(func.sum(Payment.amount)).where(
                    and_(
                        Payment.status == PaymentStatus.COMPLETED,
                        Payment.created_at >= week_start,
                        *org_filter,
                    )
                )
            )
            weekly_earnings = weekly_earnings_result.scalar() or 0

            # Calculate monthly earnings (last 30 days)
            monthly_earnings_result = await self.db.execute(
                select(func.sum(Payment.amount)).where(
                    and_(
                        Payment.status == PaymentStatus.COMPLETED,
                        Payment.created_at >= month_start,
                        *org_filter,
                    )
                )
            )
            monthly_earnings = monthly_earnings_result.scalar() or 0

            return {
                "total_payments": total_payments,
                "successful_payments": successful_payments,
                "failed_payments": failed_payments,
                "pending_payments": pending_payments,
                "total_amount": float(total_amount),
                "mpesa_payments": mpesa_payments,
                "cash_payments": cash_payments,
                "bank_transfer_payments": bank_transfer_payments,
                "daily_earnings": float(daily_earnings),
                "weekly_earnings": float(weekly_earnings),
                "monthly_earnings": float(monthly_earnings),
            }

        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting payment statistics: {e}")
            raise BillingError(f"Failed to get payment statistics: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error getting payment statistics: {e}")
            raise BillingError(f"Unexpected error: {e}")
