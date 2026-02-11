"""Seed script for subscriptions and billing data."""

import asyncio
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.subscription import Subscription, SubscriptionUsageLog, SubscriptionHistory, SubscriptionStatus, SubscriptionType
from app.models.billing import Invoice, InvoiceItem, Payment, PaymentLog, InvoiceStatus, PaymentStatus, PaymentMethod
from app.models.plan import BillingCycle as PlanBillingCycle
from app.models.user import User, UserRole
from app.models.plan import ServicePlan
from app.models.router import Router, RouterStatus

logger = get_logger(__name__)


class SubscriptionSeeder:
    """Subscription and billing data seeder."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def seed_subscriptions(self, count: int = 100, clear_existing: bool = False) -> List[Subscription]:
        """Seed subscriptions with realistic data."""
        if clear_existing:
            await self._clear_subscriptions()
            if count == 0:
                return []

        # Get available users, plans, and routers
        users = await self._get_customer_users()
        plans = await self._get_active_plans()
        routers = await self._get_active_routers()
        
        if not users or not plans or not routers:
            self.logger.error("Missing required data: users, plans, or routers")
            return []

        subscriptions = []
        
        for i in range(min(count, len(users))):
            user = users[i % len(users)]
            plan = random.choice(plans)
            router = random.choice(routers)
            
            subscription = await self._create_subscription(user, plan, router)
            subscriptions.append(subscription)
            
            # Create billing data for subscription
            await self._create_subscription_billing(subscription)
        
        await self.db.commit()
        
        self.logger.info(f"Seeded {len(subscriptions)} subscriptions")
        return subscriptions

    async def _create_subscription(self, user: User, plan: ServicePlan, router: Router) -> Subscription:
        """Create a subscription."""
        # Determine subscription type based on plan
        if plan.plan_type.value == "hotspot":
            subscription_type = SubscriptionType.HOTSPOT
            username = f"hs_{user.username}_{random.randint(100, 999)}"
        elif plan.plan_type.value == "pppoe":
            subscription_type = SubscriptionType.PPPOE
            username = f"ppp_{user.username}_{random.randint(100, 999)}"
        else:  # both
            subscription_type = random.choice([SubscriptionType.HOTSPOT, SubscriptionType.PPPOE])
            prefix = "hs" if subscription_type == SubscriptionType.HOTSPOT else "ppp"
            username = f"{prefix}_{user.username}_{random.randint(100, 999)}"
        
        # Generate password
        password = f"pass{random.randint(1000, 9999)}"
        
        # Set subscription dates
        start_date = datetime.utcnow() - timedelta(days=random.randint(1, 90))
        
        # Get plan pricing and plan billing cycle to determine validity
        plan_pricing = plan.pricing[0] if plan.pricing else None
        plan_billing_cycle = plan.billing_cycle if hasattr(plan, "billing_cycle") else PlanBillingCycle.ONE_TIME
        if plan_billing_cycle == PlanBillingCycle.MONTHLY:
            end_date = start_date + timedelta(days=30)
        elif plan_billing_cycle == PlanBillingCycle.WEEKLY:
            end_date = start_date + timedelta(days=7)
        else:
            end_date = start_date + timedelta(days=1)
        
        # Determine status
        if end_date < datetime.utcnow():
            status = random.choice([SubscriptionStatus.EXPIRED, SubscriptionStatus.SUSPENDED])
        else:
            status = random.choice([
                SubscriptionStatus.ACTIVE, SubscriptionStatus.ACTIVE, SubscriptionStatus.ACTIVE,
                SubscriptionStatus.SUSPENDED, SubscriptionStatus.PENDING
            ])  # 60% active

        # Ensure numeric fields fit in int32 to avoid DB insertion errors
        max_int32 = 2_147_483_647
        bytes_uploaded_val = min(random.randint(1000000, 100000000), max_int32)  # 1MB to 100MB
        bytes_downloaded_val = min(random.randint(100000000, 10000000000), max_int32)  # 100MB to 10GB, clamped
        total_bytes_used_val = min(random.randint(101000000, 10100000000), max_int32)

        subscription = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            router_id=router.id,
            subscription_type=subscription_type,
            status=status,
            username=username,
            password=password,  # In production, this would be encrypted
            start_date=start_date,
            end_date=end_date,
            is_auto_renewal=random.choice([True, False]),
            bytes_uploaded=bytes_uploaded_val,
            bytes_downloaded=bytes_downloaded_val,
            total_bytes_used=total_bytes_used_val,
            session_count=random.randint(1, 100),
            last_activity=datetime.utcnow() - timedelta(hours=random.randint(1, 24)) if status == SubscriptionStatus.ACTIVE else None,
            router_config=self._get_subscription_router_config(subscription_type),
            is_router_synced=random.choice([True, False]),
            last_router_sync=datetime.utcnow() - timedelta(hours=random.randint(1, 48)) if random.choice([True, False]) else None,
            notes=f"Seeded subscription for {user.username}",
            created_by=user.id,
            created_at=start_date
        )
        
        self.db.add(subscription)
        await self.db.flush()
        
        # Create usage logs
        await self._create_subscription_usage_logs(subscription)
        
        return subscription

    async def _create_subscription_usage_logs(self, subscription: Subscription):
        """Create usage logs for a subscription."""
        # Create daily usage logs since subscription start
        days_active = (datetime.utcnow() - subscription.start_date).days
        days_to_log = min(days_active, 30)  # Log last 30 days max
        
        for i in range(days_to_log):
            log_date = datetime.utcnow().date() - timedelta(days=i)
            
            # Simulate realistic usage patterns
            if subscription.status == SubscriptionStatus.ACTIVE:
                bytes_used = random.randint(10000000, 500000000)  # 10MB to 500MB per day
                session_duration = random.randint(30, 480)  # 30 minutes to 8 hours
                sessions = random.randint(1, 10)
            else:
                bytes_used = 0
                session_duration = 0
                sessions = 0
            
            usage_log = SubscriptionUsageLog(
                subscription_id=subscription.id,
                log_date=log_date,
                bytes_uploaded=bytes_used // 10,  # 10% upload
                bytes_downloaded=bytes_used,
                session_duration=session_duration * 60,  # convert minutes to seconds
                ip_address=None,
                mac_address=None
            )
            
            self.db.add(usage_log)

    async def _create_subscription_billing(self, subscription: Subscription):
        """Create billing data for a subscription."""
        # Get plan pricing
        plan_pricing = subscription.plan.pricing[0] if subscription.plan.pricing else None
        if not plan_pricing:
            return
        
        # Create invoices based on billing cycle
        billing_start = subscription.start_date
        current_date = datetime.utcnow()
        
        invoice_count = 0
        while billing_start < current_date and invoice_count < 12:  # Max 12 invoices
            plan_billing_cycle = subscription.plan.billing_cycle if hasattr(subscription.plan, "billing_cycle") else PlanBillingCycle.ONE_TIME
            if plan_billing_cycle == PlanBillingCycle.MONTHLY:
                billing_end = billing_start + timedelta(days=30)
            elif plan_billing_cycle == PlanBillingCycle.WEEKLY:
                billing_end = billing_start + timedelta(days=7)
            else:  # ONE_TIME
                billing_end = billing_start + timedelta(days=1)
            
            invoice = await self._create_invoice(subscription, plan_pricing, billing_start, billing_end)
            
            # Create payment for invoice (80% payment rate)
            if random.random() < 0.8:
                await self._create_payment(invoice)
            
            billing_start = billing_end
            invoice_count += 1

    async def _create_invoice(self, subscription: Subscription, plan_pricing, billing_start: datetime, billing_end: datetime) -> Invoice:
        """Create an invoice for a subscription."""
        invoice_number = f"INV-{subscription.id}-{billing_start.strftime('%Y%m%d')}"
        
        # Calculate amounts
        subtotal = plan_pricing.price
        tax_amount = subtotal * Decimal("0.16")  # 16% VAT
        total_amount = subtotal + tax_amount
        
        # Determine status
        if billing_end < datetime.utcnow():
            status = random.choice([InvoiceStatus.PAID, InvoiceStatus.OVERDUE])
        else:
            status = random.choice([InvoiceStatus.PENDING, InvoiceStatus.DRAFT])

        invoice = Invoice(
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            invoice_number=invoice_number,
            status=status,
            subtotal=subtotal,
            tax_amount=tax_amount,
            discount_amount=Decimal("0.00"),
            total_amount=total_amount,
            paid_amount=total_amount if status == InvoiceStatus.PAID else Decimal("0.00"),
            balance=Decimal("0.00") if status == InvoiceStatus.PAID else total_amount,
            issue_date=billing_start,
            due_date=billing_start + timedelta(days=7),
            paid_date=billing_start + timedelta(days=random.randint(1, 7)) if status == InvoiceStatus.PAID else None,
            billing_period_start=billing_start,
            billing_period_end=billing_end,
            currency="KES",
            notes=f"Invoice for {subscription.plan.name}",
            terms="Payment due within 7 days of invoice date"
        )
        
        self.db.add(invoice)
        await self.db.flush()
        
        # Create invoice items
        item = InvoiceItem(
            invoice_id=invoice.id,
            description=f"{subscription.plan.name} - {billing_start.strftime('%B %Y')}",
            quantity=1,
            unit_price=subtotal,
            total_price=subtotal,
            item_type="subscription",
        )
        
        self.db.add(item)
        
        return invoice

    async def _create_payment(self, invoice: Invoice):
        """Create a payment for an invoice."""
        payment_methods = [PaymentMethod.MPESA, PaymentMethod.BANK_TRANSFER, PaymentMethod.CASH]
        payment_method = random.choice(payment_methods)
        
        payment = Payment(
            user_id=invoice.user_id,
            invoice_id=invoice.id,
            amount=invoice.total_amount,
            payment_method=payment_method,
            payment_number=f"PAY{random.randint(100000, 999999)}",
            reference_number=f"MP{random.randint(100000000, 999999999)}" if payment_method == PaymentMethod.MPESA else f"TXN{random.randint(100000, 999999)}",
            status=PaymentStatus.COMPLETED,
            payment_date=invoice.paid_date or datetime.utcnow(),
            currency="KES",
            mpesa_receipt_number=f"MP{random.randint(100000000, 999999999)}" if payment_method == PaymentMethod.MPESA else None,
            mpesa_phone_number=invoice.user.phone if payment_method == PaymentMethod.MPESA else None,
            notes=f"Payment for invoice {invoice.invoice_number}"
        )
        
        self.db.add(payment)
        
        # Update invoice status
        invoice.status = InvoiceStatus.PAID
        invoice.paid_amount = invoice.total_amount
        invoice.balance = Decimal("0.00")

    def _get_subscription_router_config(self, subscription_type: SubscriptionType) -> str:
        """Get router configuration for subscription type."""
        if subscription_type == SubscriptionType.HOTSPOT:
            config = {
                "type": "hotspot",
                "profile": "default",
                "rate_limit": "5M/2M",
                "session_timeout": "1d",
                "idle_timeout": "30m",
                "shared_users": 1
            }
        else:  # PPPoE
            config = {
                "type": "pppoe",
                "profile": "default-ppp",
                "rate_limit": "10M/5M",
                "local_address": "172.31.1.1",
                "remote_address": "172.31.2.0/24"
            }
        
        import json
        return json.dumps(config)

    async def _get_customer_users(self) -> List[User]:
        """Get customer users for subscriptions."""
        result = await self.db.execute(
            select(User).where(User.role == UserRole.CUSTOMER).limit(200)
        )
        return result.scalars().all()

    async def _get_active_plans(self) -> List[ServicePlan]:
        """Get active service plans with pricing eagerly loaded."""
        from app.models.plan import PlanStatus
        from sqlalchemy.orm import selectinload

        result = await self.db.execute(
            select(ServicePlan).options(selectinload(ServicePlan.pricing_tiers)).where(ServicePlan.status == PlanStatus.ACTIVE).limit(50)
        )
        return result.scalars().all()

    async def _get_active_routers(self) -> List[Router]:
        """Get active routers."""
        result = await self.db.execute(
            select(Router).where(Router.is_active == True).limit(20)
        )
        return result.scalars().all()

    async def _clear_subscriptions(self):
        """Clear existing subscriptions and related billing data."""
        from sqlalchemy import delete
        
        # Delete in correct order to respect foreign key constraints
        await self.db.execute(delete(PaymentLog))
        await self.db.execute(delete(Payment))
        await self.db.execute(delete(InvoiceItem))
        await self.db.execute(delete(Invoice))
        await self.db.execute(delete(SubscriptionHistory))
        await self.db.execute(delete(SubscriptionUsageLog))
        await self.db.execute(delete(Subscription))
        
        await self.db.commit()
        self.logger.info("Cleared existing subscriptions and billing data")


async def seed_subscriptions(count: int = 100, clear_existing: bool = False) -> List[Subscription]:
    """Seed subscriptions."""
    async with AsyncSessionLocal() as db:
        seeder = SubscriptionSeeder(db)
        return await seeder.seed_subscriptions(count, clear_existing)


if __name__ == "__main__":
    asyncio.run(seed_subscriptions(count=100, clear_existing=True))
