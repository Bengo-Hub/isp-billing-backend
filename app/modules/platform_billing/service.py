"""
Platform Billing Service.

Handles ISP provider subscription billing:
- Invoice generation based on tier + earnings
- Payment processing via Paystack
- Subscription management
- Earnings tracking
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple
import uuid

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.organization import Organization, OrganizationStatus
from app.models.platform_billing import (
    PlatformSubscriptionTier,
    PlatformInvoice,
    PlatformPayment,
    EarningsRecord,
    BillingCycle,
    TierType,
    InvoiceStatus,
    PaymentStatus,
)
from app.models.billing import Payment
from app.integrations.payment_gateways import PaystackGateway

logger = logging.getLogger(__name__)


class PlatformBillingService:
    """
    Service for managing platform billing.

    Handles:
    - Calculating monthly fees (base + earnings percentage)
    - Generating invoices for ISP providers
    - Processing payments via Paystack
    - Managing subscription tiers
    - Handling subscription expiry and suspension
    """

    def __init__(self, db: AsyncSession):
        """Initialize the service with database session."""
        self.db = db
        self._paystack: Optional[PaystackGateway] = None

    @property
    def paystack(self) -> PaystackGateway:
        """Get Paystack gateway for platform billing."""
        if self._paystack is None:
            self._paystack = PaystackGateway({
                "credentials": {
                    "secret_key": getattr(settings, "platform_paystack_secret_key", ""),
                    "public_key": getattr(settings, "platform_paystack_public_key", ""),
                },
                "callback_url": getattr(settings, "platform_paystack_callback_url", ""),
            })
        return self._paystack

    # =========================================================================
    # Subscription Tier Management
    # =========================================================================

    async def get_subscription_tiers(
        self,
        tier_type: Optional[TierType] = None,
        active_only: bool = True,
    ) -> List[PlatformSubscriptionTier]:
        """Get all subscription tiers."""
        query = select(PlatformSubscriptionTier)

        if tier_type:
            query = query.where(PlatformSubscriptionTier.tier_type == tier_type)

        if active_only:
            query = query.where(PlatformSubscriptionTier.is_active == True)

        query = query.order_by(PlatformSubscriptionTier.display_order)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_subscription_tier(self, tier_id: int) -> Optional[PlatformSubscriptionTier]:
        """Get a specific subscription tier."""
        result = await self.db.execute(
            select(PlatformSubscriptionTier).where(PlatformSubscriptionTier.id == tier_id)
        )
        return result.scalar_one_or_none()

    async def get_default_tier(self, tier_type: TierType) -> Optional[PlatformSubscriptionTier]:
        """Get the default tier for a type."""
        result = await self.db.execute(
            select(PlatformSubscriptionTier).where(
                PlatformSubscriptionTier.tier_type == tier_type,
                PlatformSubscriptionTier.is_default == True,
                PlatformSubscriptionTier.is_active == True,
            )
        )
        tier = result.scalar_one_or_none()

        # If no default, get the first active tier
        if not tier:
            result = await self.db.execute(
                select(PlatformSubscriptionTier).where(
                    PlatformSubscriptionTier.tier_type == tier_type,
                    PlatformSubscriptionTier.is_active == True,
                ).order_by(PlatformSubscriptionTier.display_order).limit(1)
            )
            tier = result.scalar_one_or_none()

        return tier

    async def create_subscription_tier(
        self,
        data: dict,
    ) -> PlatformSubscriptionTier:
        """Create a new subscription tier."""
        tier = PlatformSubscriptionTier(**data)
        self.db.add(tier)
        await self.db.commit()
        await self.db.refresh(tier)
        return tier

    async def update_subscription_tier(
        self,
        tier_id: int,
        data: dict,
    ) -> Optional[PlatformSubscriptionTier]:
        """Update a subscription tier."""
        tier = await self.get_subscription_tier(tier_id)
        if not tier:
            return None

        for key, value in data.items():
            if value is not None and hasattr(tier, key):
                setattr(tier, key, value)

        await self.db.commit()
        await self.db.refresh(tier)
        return tier

    # =========================================================================
    # Earnings Calculation
    # =========================================================================

    async def get_organization_earnings(
        self,
        organization_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> Tuple[Decimal, int]:
        """
        Get organization earnings for a period.

        Returns:
            Tuple of (total_earnings, customer_count)
        """
        # Sum from earnings_records table
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(EarningsRecord.net_amount), 0),
                func.coalesce(func.max(EarningsRecord.active_customers), 0),
            ).where(
                EarningsRecord.organization_id == organization_id,
                EarningsRecord.date >= start_date,
                EarningsRecord.date < end_date,
            )
        )
        row = result.one()
        total_earnings = Decimal(str(row[0] or 0))
        customer_count = int(row[1] or 0)

        # If no earnings records, calculate from payments
        if total_earnings == 0:
            payment_result = await self.db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.organization_id == organization_id,
                    Payment.status == "completed",
                    Payment.created_at >= start_date,
                    Payment.created_at < end_date,
                )
            )
            total_earnings = Decimal(str(payment_result.scalar() or 0))

        return total_earnings, customer_count

    async def record_daily_earnings(
        self,
        organization_id: int,
        date: datetime,
        earnings_data: dict,
    ) -> EarningsRecord:
        """Record daily earnings for an organization."""
        # Check if record exists
        result = await self.db.execute(
            select(EarningsRecord).where(
                EarningsRecord.organization_id == organization_id,
                func.date(EarningsRecord.date) == date.date(),
            )
        )
        record = result.scalar_one_or_none()

        if record:
            # Update existing record
            for key, value in earnings_data.items():
                if hasattr(record, key):
                    setattr(record, key, value)
        else:
            # Create new record
            record = EarningsRecord(
                organization_id=organization_id,
                date=date,
                **earnings_data,
            )
            self.db.add(record)

        await self.db.commit()
        await self.db.refresh(record)
        return record

    # =========================================================================
    # Invoice Management
    # =========================================================================

    async def calculate_invoice_amount(
        self,
        organization: Organization,
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        """
        Calculate invoice amount for an organization.

        For Hotspot:
        - Base fee (500 KES)
        - 2% of earnings above 10,000 KES threshold

        For PPPoE:
        - Base fee based on tier
        - Per-customer fee if applicable
        """
        tier = None
        if organization.subscription_tier_id:
            tier = await self.get_subscription_tier(organization.subscription_tier_id)

        if not tier:
            tier = await self.get_default_tier(
                TierType.HOTSPOT if organization.organization_type == "hotspot"
                else TierType.PPPOE
            )

        if not tier:
            # Fallback values
            base_fee = Decimal("500")
            earnings_threshold = Decimal("10000")
            earnings_percentage = Decimal("2.0")
        else:
            base_fee = tier.base_monthly_fee
            earnings_threshold = tier.earnings_threshold
            earnings_percentage = tier.earnings_percentage

        # Get earnings and customer count
        earnings, customer_count = await self.get_organization_earnings(
            organization.id, start_date, end_date
        )

        # Calculate earnings fee (for Hotspot)
        earnings_fee = Decimal("0")
        if tier and tier.tier_type == TierType.HOTSPOT:
            if earnings > earnings_threshold:
                excess = earnings - earnings_threshold
                earnings_fee = (excess * earnings_percentage) / Decimal("100")

        # Calculate customer fee (for PPPoE)
        customer_fee = Decimal("0")
        if tier and tier.tier_type == TierType.PPPOE and tier.per_customer_fee:
            customer_fee = tier.per_customer_fee * customer_count

        # Calculate total
        total = base_fee + earnings_fee + customer_fee

        return {
            "tier_id": tier.id if tier else None,
            "base_fee": base_fee,
            "earnings_during_period": earnings,
            "earnings_fee": earnings_fee,
            "customer_count": customer_count,
            "customer_fee": customer_fee,
            "additional_fees": Decimal("0"),
            "discount": Decimal("0"),
            "tax": Decimal("0"),
            "total_amount": total,
        }

    async def generate_invoice(
        self,
        organization_id: int,
        billing_period_start: datetime,
        billing_period_end: datetime,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY,
    ) -> PlatformInvoice:
        """Generate an invoice for an organization."""
        # Get organization
        result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            raise ValueError(f"Organization {organization_id} not found")

        # Calculate amounts
        amounts = await self.calculate_invoice_amount(
            organization, billing_period_start, billing_period_end
        )

        # Generate invoice number
        invoice_number = self._generate_invoice_number()

        # Set due date (7 days after end of billing period)
        due_date = billing_period_end + timedelta(days=7)

        # Create invoice
        invoice = PlatformInvoice(
            organization_id=organization_id,
            invoice_number=invoice_number,
            billing_cycle=billing_cycle,
            billing_period_start=billing_period_start,
            billing_period_end=billing_period_end,
            due_date=due_date,
            status=InvoiceStatus.PENDING,
            **amounts,
        )

        self.db.add(invoice)
        await self.db.commit()
        await self.db.refresh(invoice)

        logger.info(f"Generated invoice {invoice_number} for org {organization_id}: {amounts['total_amount']} KES")

        return invoice

    async def generate_monthly_invoices(
        self,
        organization_ids: Optional[List[int]] = None,
    ) -> List[PlatformInvoice]:
        """Generate monthly invoices for all or specified organizations."""
        # Calculate billing period (previous month)
        today = datetime.utcnow()
        first_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        billing_period_end = first_of_month
        billing_period_start = (first_of_month - timedelta(days=1)).replace(day=1)

        # Get organizations
        query = select(Organization).where(
            Organization.status.in_([OrganizationStatus.ACTIVE, OrganizationStatus.TRIAL])
        )

        if organization_ids:
            query = query.where(Organization.id.in_(organization_ids))

        result = await self.db.execute(query)
        organizations = list(result.scalars().all())

        invoices = []
        for org in organizations:
            try:
                invoice = await self.generate_invoice(
                    org.id,
                    billing_period_start,
                    billing_period_end,
                )
                invoices.append(invoice)
            except Exception as e:
                logger.error(f"Failed to generate invoice for org {org.id}: {e}")

        return invoices

    async def get_invoice(self, invoice_id: int) -> Optional[PlatformInvoice]:
        """Get an invoice by ID."""
        result = await self.db.execute(
            select(PlatformInvoice)
            .options(selectinload(PlatformInvoice.organization))
            .where(PlatformInvoice.id == invoice_id)
        )
        return result.scalar_one_or_none()

    async def get_organization_invoices(
        self,
        organization_id: int,
        status: Optional[InvoiceStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[PlatformInvoice]:
        """Get invoices for an organization."""
        query = select(PlatformInvoice).where(
            PlatformInvoice.organization_id == organization_id
        )

        if status:
            query = query.where(PlatformInvoice.status == status)

        query = query.order_by(PlatformInvoice.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_pending_invoices(self) -> List[PlatformInvoice]:
        """Get all pending invoices."""
        result = await self.db.execute(
            select(PlatformInvoice)
            .options(selectinload(PlatformInvoice.organization))
            .where(PlatformInvoice.status == InvoiceStatus.PENDING)
            .order_by(PlatformInvoice.due_date)
        )
        return list(result.scalars().all())

    async def get_overdue_invoices(self) -> List[PlatformInvoice]:
        """Get all overdue invoices."""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(PlatformInvoice)
            .options(selectinload(PlatformInvoice.organization))
            .where(
                PlatformInvoice.status == InvoiceStatus.PENDING,
                PlatformInvoice.due_date < now,
            )
            .order_by(PlatformInvoice.due_date)
        )
        return list(result.scalars().all())

    async def mark_overdue_invoices(self) -> int:
        """Mark overdue invoices as OVERDUE status."""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(PlatformInvoice).where(
                PlatformInvoice.status == InvoiceStatus.PENDING,
                PlatformInvoice.due_date < now,
            )
        )
        invoices = list(result.scalars().all())

        count = 0
        for invoice in invoices:
            invoice.status = InvoiceStatus.OVERDUE
            count += 1

        await self.db.commit()
        return count

    # =========================================================================
    # Payment Processing
    # =========================================================================

    async def initiate_payment(
        self,
        invoice_id: int,
        email: str,
    ) -> dict:
        """
        Initiate payment for an invoice via Paystack.

        Returns checkout URL for the customer.
        """
        invoice = await self.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        if invoice.status == InvoiceStatus.PAID:
            raise ValueError("Invoice is already paid")

        reference = f"PLAT-{invoice.invoice_number}-{uuid.uuid4().hex[:8].upper()}"

        result = await self.paystack.initiate_payment(
            amount=invoice.total_amount,
            phone_number="",  # Not needed for Paystack
            reference=reference,
            description=f"Platform Subscription - Invoice {invoice.invoice_number}",
            metadata={
                "email": email,
                "invoice_id": invoice.id,
                "organization_id": invoice.organization_id,
            },
        )

        if result.success:
            # Store reference on invoice
            invoice.paystack_reference = reference
            await self.db.commit()

        return {
            "success": result.success,
            "checkout_url": result.checkout_url,
            "reference": reference,
            "message": result.message,
        }

    async def process_payment_callback(
        self,
        callback_data: dict,
    ) -> Optional[PlatformPayment]:
        """Process Paystack payment callback."""
        result = await self.paystack.process_callback(callback_data)

        if not result.success:
            logger.warning(f"Payment callback failed: {result.message}")
            return None

        # Find the invoice by reference
        reference = result.transaction_reference
        invoice_result = await self.db.execute(
            select(PlatformInvoice).where(
                PlatformInvoice.paystack_reference == reference
            )
        )
        invoice = invoice_result.scalar_one_or_none()

        if not invoice:
            logger.error(f"Invoice not found for reference: {reference}")
            return None

        # Create payment record
        payment = PlatformPayment(
            invoice_id=invoice.id,
            organization_id=invoice.organization_id,
            payment_reference=f"PAY-{reference}",
            amount=result.amount or invoice.total_amount,
            currency=result.currency or "KES",
            paystack_reference=result.gateway_reference,
            status=PaymentStatus.COMPLETED,
            callback_data=result.raw_data,
            completed_at=result.paid_at or datetime.utcnow(),
        )

        self.db.add(payment)

        # Update invoice
        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = result.paid_at or datetime.utcnow()

        # Update organization subscription
        org = await self.db.execute(
            select(Organization).where(Organization.id == invoice.organization_id)
        )
        organization = org.scalar_one_or_none()

        if organization:
            # Extend subscription based on billing cycle
            if invoice.billing_cycle == BillingCycle.MONTHLY:
                extension = timedelta(days=30)
            elif invoice.billing_cycle == BillingCycle.QUARTERLY:
                extension = timedelta(days=90)
            else:
                extension = timedelta(days=365)

            if organization.subscription_ends_at:
                organization.subscription_ends_at = max(
                    organization.subscription_ends_at,
                    datetime.utcnow()
                ) + extension
            else:
                organization.subscription_ends_at = datetime.utcnow() + extension

            if organization.status == OrganizationStatus.PENDING_PAYMENT:
                organization.status = OrganizationStatus.ACTIVE

        await self.db.commit()
        await self.db.refresh(payment)

        logger.info(f"Processed payment for invoice {invoice.invoice_number}")

        return payment

    async def record_manual_payment(
        self,
        invoice_id: int,
        amount: Decimal,
        reference: str,
        notes: Optional[str] = None,
    ) -> PlatformPayment:
        """Record a manual payment (e.g., bank transfer)."""
        invoice = await self.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        payment = PlatformPayment(
            invoice_id=invoice.id,
            organization_id=invoice.organization_id,
            payment_reference=reference,
            amount=amount,
            currency="KES",
            status=PaymentStatus.COMPLETED,
            completed_at=datetime.utcnow(),
        )

        self.db.add(payment)

        if amount >= invoice.total_amount:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(payment)

        return payment

    # =========================================================================
    # Subscription Management
    # =========================================================================

    async def handle_subscription_expiry(
        self,
        organization_id: int,
    ) -> bool:
        """Handle expired subscription."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            return False

        if organization.is_subscription_active:
            return False  # Not expired

        # Mark as pending payment
        organization.status = OrganizationStatus.PENDING_PAYMENT

        await self.db.commit()

        logger.info(f"Organization {organization_id} marked as pending payment")

        return True

    async def suspend_organization(
        self,
        organization_id: int,
        reason: Optional[str] = None,
    ) -> bool:
        """Suspend an organization for non-payment."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            return False

        organization.status = OrganizationStatus.SUSPENDED
        organization.suspended_at = datetime.utcnow()

        await self.db.commit()

        logger.info(f"Organization {organization_id} suspended: {reason}")

        return True

    async def reactivate_organization(
        self,
        organization_id: int,
    ) -> bool:
        """Reactivate a suspended organization."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            return False

        # Check if subscription is paid
        if not organization.is_subscription_active:
            return False

        organization.status = OrganizationStatus.ACTIVE
        organization.suspended_at = None

        await self.db.commit()

        logger.info(f"Organization {organization_id} reactivated")

        return True

    async def upgrade_tier(
        self,
        organization_id: int,
        new_tier_id: int,
    ) -> bool:
        """Upgrade organization to a new tier."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            return False

        tier = await self.get_subscription_tier(new_tier_id)
        if not tier:
            return False

        organization.subscription_tier_id = new_tier_id
        organization.max_routers = tier.max_routers
        organization.max_customers = tier.max_customers or 999999
        organization.max_users = tier.max_staff_users

        await self.db.commit()

        logger.info(f"Organization {organization_id} upgraded to tier {tier.name}")

        return True

    # =========================================================================
    # Helpers
    # =========================================================================

    def _generate_invoice_number(self) -> str:
        """Generate a unique invoice number."""
        now = datetime.utcnow()
        return f"PLAT-{now.strftime('%Y%m')}-{uuid.uuid4().hex[:8].upper()}"
