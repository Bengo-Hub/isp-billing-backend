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
from app.integrations.mpesa import MpesaService
from app.api.deps import PaginationParams
from app.core.logging import get_logger
from app.core.exceptions import BillingError, PaymentError, ValidationError
from app.core.datetime_utils import normalize_datetime


class BillingService:
    """Billing and payment management service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.mpesa_service = MpesaService()
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
        result = await self.db.execute(
            select(Subscription).where(
                and_(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.is_auto_renewal == True
                )
            )
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
    ) -> Payment:
        """Create a new payment."""
        # Generate payment number
        payment_number = await self._generate_payment_number()

        payment = Payment(
            user_id=user_id,
            invoice_id=invoice_id,
            payment_number=payment_number,
            amount=amount,
            payment_method=payment_method,
            transaction_id=transaction_id,
            reference_number=reference_number,
            notes=notes,
            status=PaymentStatus.PENDING,
        )

        self.db.add(payment)
        await self.db.commit()
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

    async def _apply_payment_to_invoice(self, invoice_id: int, amount: Decimal) -> None:
        """Apply payment to invoice."""
        invoice = await self.get_invoice_by_id(invoice_id)
        if not invoice:
            return

        # Update invoice payment
        invoice.paid_amount += amount
        invoice.balance = invoice.total_amount - invoice.paid_amount

        # Update status if fully paid
        if invoice.balance <= 0:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_date = datetime.utcnow()

        await self.db.commit()

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
        """Get overdue invoices."""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(Invoice).where(
                and_(
                    Invoice.due_date < now,
                    Invoice.status == InvoiceStatus.PENDING
                )
            )
        )
        return result.scalars().all()

    async def get_overdue_invoices(self) -> List[Invoice]:
        """Get all overdue invoices."""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(Invoice).where(
                and_(
                    Invoice.status == InvoiceStatus.PENDING,
                    Invoice.due_date < now
                )
            )
        )
        return result.scalars().all()

    async def get_billing_stats(self) -> Dict[str, Any]:
        """Get billing statistics."""
        # Total invoices
        result = await self.db.execute(select(func.count(Invoice.id)))
        total_invoices = result.scalar() or 0

        # Paid invoices
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.PAID)
        )
        paid_invoices = result.scalar() or 0

        # Pending invoices
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.PENDING)
        )
        pending_invoices = result.scalar() or 0

        # Overdue invoices
        result = await self.db.execute(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.OVERDUE)
        )
        overdue_invoices = result.scalar() or 0

        # Total revenue
        result = await self.db.execute(
            select(func.sum(Invoice.paid_amount)).where(Invoice.status == InvoiceStatus.PAID)
        )
        total_revenue = result.scalar() or 0

        # Pending revenue
        result = await self.db.execute(
            select(func.sum(Invoice.total_amount)).where(
                Invoice.status.in_([InvoiceStatus.PENDING, InvoiceStatus.OVERDUE])
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
            # Get total payments count
            total_payments_result = await self.db.execute(
                select(func.count(Payment.id))
            )
            total_payments = total_payments_result.scalar() or 0
            
            # Get successful payments count
            successful_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(Payment.status == PaymentStatus.COMPLETED)
            )
            successful_payments = successful_payments_result.scalar() or 0
            
            # Get failed payments count
            failed_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(Payment.status == PaymentStatus.FAILED)
            )
            failed_payments = failed_payments_result.scalar() or 0
            
            # Get pending payments count
            pending_payments_result = await self.db.execute(
                select(func.count(Payment.id)).where(Payment.status == PaymentStatus.PENDING)
            )
            pending_payments = pending_payments_result.scalar() or 0
            
            # Get total amount collected
            total_amount_result = await self.db.execute(
                select(func.sum(Payment.amount)).where(Payment.status == PaymentStatus.COMPLETED)
            )
            total_amount = total_amount_result.scalar() or 0
            
            # Get average payment amount
            avg_amount_result = await self.db.execute(
                select(func.avg(Payment.amount)).where(Payment.status == PaymentStatus.COMPLETED)
            )
            avg_amount = avg_amount_result.scalar() or 0
            
            # Calculate success rate
            success_rate = (successful_payments / total_payments * 100) if total_payments > 0 else 0
            
            return {
                "total_payments": total_payments,
                "successful_payments": successful_payments,
                "failed_payments": failed_payments,
                "pending_payments": pending_payments,
                "total_amount": float(total_amount),
                "average_amount": float(avg_amount),
                "success_rate": round(success_rate, 2)
            }
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting payment statistics: {e}")
            raise BillingError(f"Failed to get payment statistics: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error getting payment statistics: {e}")
            raise BillingError(f"Unexpected error: {e}")
