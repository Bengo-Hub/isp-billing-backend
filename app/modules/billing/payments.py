"""Enhanced payment management service with status tracking and bulk operations."""

import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_, desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, PaymentError
from app.models.billing import (
    Payment,
    PaymentStatus,
    PaymentMethod,
    Invoice,
    InvoiceStatus
)
from app.models.user import User
from app.api.deps import PaginationParams

logger = get_logger(__name__)


class PaymentManagementService:
    """Enhanced payment management service with advanced features."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def record_manual_payment(
        self,
        payment_data: Dict[str, Any],
        recorded_by: int,
        receipt_image_url: Optional[str] = None
    ) -> Payment:
        """Record a manual payment."""
        try:
            # Generate payment number
            payment_number = self._generate_payment_number("MANUAL")

            # Create payment record
            payment = Payment(
                payment_number=payment_number,
                user_id=payment_data['user_id'],
                invoice_id=payment_data.get('invoice_id'),
                amount=payment_data['amount'],
                currency=payment_data.get('currency', 'KES'),
                payment_method=PaymentMethod.CASH if payment_data.get('payment_method') == 'cash' else PaymentMethod.BANK_TRANSFER,
                status=PaymentStatus.UNCHECKED,  # Manual payments need verification
                is_manual_payment=True,
                recorded_by=recorded_by,
                receipt_image_url=receipt_image_url,
                reference_number=payment_data.get('reference_number'),
                notes=payment_data.get('notes'),
                payment_date=payment_data.get('payment_date', datetime.utcnow())
            )

            self.db.add(payment)
            await self.db.commit()
            await self.db.refresh(payment)

            self.logger.info(f"Recorded manual payment {payment_number} for user {payment_data['user_id']}")
            return payment

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to record manual payment: {e}")
            raise

    async def verify_payment(
        self,
        payment_id: int,
        verified_by: int,
        verification_status: PaymentStatus,
        verification_notes: Optional[str] = None
    ) -> bool:
        """Verify a payment and update its status."""
        payment = await self.db.get(Payment, payment_id)
        if not payment:
            return False

        try:
            # Update payment verification
            payment.status = verification_status
            payment.verified_by = verified_by
            payment.verified_at = datetime.utcnow()
            payment.verification_notes = verification_notes

            # If payment is verified as completed, update related invoice
            if verification_status == PaymentStatus.CHECKED and payment.invoice_id:
                invoice = await self.db.get(Invoice, payment.invoice_id)
                if invoice:
                    # Update invoice paid amount
                    invoice.paid_amount += payment.amount
                    invoice.balance = invoice.total_amount - invoice.paid_amount
                    
                    # Update invoice status if fully paid
                    if invoice.balance <= 0:
                        invoice.status = InvoiceStatus.PAID
                        invoice.paid_date = datetime.utcnow()

            await self.db.commit()

            self.logger.info(f"Verified payment {payment.payment_number} as {verification_status.value}")
            return True

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to verify payment {payment_id}: {e}")
            return False

    async def bulk_verify_payments(
        self,
        payment_ids: List[int],
        verification_status: PaymentStatus,
        verified_by: int,
        verification_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Bulk verify multiple payments."""
        try:
            successful = 0
            failed = 0
            results = []

            for payment_id in payment_ids:
                try:
                    success = await self.verify_payment(
                        payment_id=payment_id,
                        verified_by=verified_by,
                        verification_status=verification_status,
                        verification_notes=verification_notes
                    )
                    
                    if success:
                        successful += 1
                        results.append({"payment_id": payment_id, "success": True})
                    else:
                        failed += 1
                        results.append({"payment_id": payment_id, "success": False, "error": "Payment not found"})

                except Exception as e:
                    failed += 1
                    results.append({"payment_id": payment_id, "success": False, "error": str(e)})

            return {
                "total_processed": len(payment_ids),
                "successful": successful,
                "failed": failed,
                "results": results
            }

        except Exception as e:
            self.logger.error(f"Failed to bulk verify payments: {e}")
            raise

    async def get_payments_by_status(
        self,
        pagination: PaginationParams,
        status: PaymentStatus,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        user_id: Optional[int] = None,
        payment_method: Optional[PaymentMethod] = None
    ) -> Dict[str, Any]:
        """Get payments filtered by status and other criteria."""
        query = select(Payment).where(Payment.status == status)

        # Apply additional filters
        if start_date:
            query = query.where(Payment.created_at >= start_date)
        if end_date:
            query = query.where(Payment.created_at <= end_date)
        if user_id:
            query = query.where(Payment.user_id == user_id)
        if payment_method:
            query = query.where(Payment.payment_method == payment_method)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get payments with pagination
        query = query.order_by(desc(Payment.created_at))
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

    async def get_payment_statistics(
        self,
        days: int = 30,
        group_by: str = "status"
    ) -> Dict[str, Any]:
        """Get payment statistics."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        if group_by == "status":
            # Group by payment status
            result = await self.db.execute(
                select(
                    Payment.status,
                    func.count(Payment.id).label('count'),
                    func.sum(Payment.amount).label('total_amount')
                )
                .where(Payment.created_at >= start_date)
                .group_by(Payment.status)
            )
            
            stats = {}
            total_payments = 0
            total_amount = Decimal('0')
            
            for row in result:
                stats[row.status.value] = {
                    "count": row.count,
                    "total_amount": float(row.total_amount or 0)
                }
                total_payments += row.count
                total_amount += row.total_amount or 0

        elif group_by == "method":
            # Group by payment method
            result = await self.db.execute(
                select(
                    Payment.payment_method,
                    func.count(Payment.id).label('count'),
                    func.sum(Payment.amount).label('total_amount')
                )
                .where(Payment.created_at >= start_date)
                .group_by(Payment.payment_method)
            )
            
            stats = {}
            total_payments = 0
            total_amount = Decimal('0')
            
            for row in result:
                stats[row.payment_method.value] = {
                    "count": row.count,
                    "total_amount": float(row.total_amount or 0)
                }
                total_payments += row.count
                total_amount += row.total_amount or 0

        else:
            raise ValidationError(f"Invalid group_by parameter: {group_by}")

        # Calculate additional metrics
        verified_payments = await self.db.execute(
            select(func.count(Payment.id))
            .where(
                and_(
                    Payment.created_at >= start_date,
                    Payment.status == PaymentStatus.CHECKED
                )
            )
        )
        verified_count = verified_payments.scalar() or 0

        unverified_payments = await self.db.execute(
            select(func.count(Payment.id))
            .where(
                and_(
                    Payment.created_at >= start_date,
                    Payment.status == PaymentStatus.UNCHECKED
                )
            )
        )
        unverified_count = unverified_payments.scalar() or 0

        verification_rate = (verified_count / total_payments * 100) if total_payments > 0 else 0

        return {
            "period_days": days,
            "group_by": group_by,
            "total_payments": total_payments,
            "total_amount": float(total_amount),
            "verification_rate": round(verification_rate, 2),
            "verified_payments": verified_count,
            "unverified_payments": unverified_count,
            "breakdown": stats
        }

    async def bulk_update_payment_status(
        self,
        payment_ids: List[int],
        new_status: PaymentStatus,
        updated_by: int,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Bulk update payment status."""
        try:
            # Validate payments exist
            result = await self.db.execute(
                select(Payment).where(Payment.id.in_(payment_ids))
            )
            payments = result.scalars().all()
            
            if len(payments) != len(payment_ids):
                found_ids = [p.id for p in payments]
                missing_ids = [pid for pid in payment_ids if pid not in found_ids]
                raise ValidationError(f"Payments not found: {missing_ids}")

            # Update payments
            update_data = {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
            
            if new_status in [PaymentStatus.CHECKED, PaymentStatus.UNCHECKED]:
                update_data["verified_by"] = updated_by
                update_data["verified_at"] = datetime.utcnow()
                update_data["verification_notes"] = notes

            await self.db.execute(
                update(Payment)
                .where(Payment.id.in_(payment_ids))
                .values(**update_data)
            )

            # Update related invoices if payments are verified as completed
            if new_status == PaymentStatus.CHECKED:
                for payment in payments:
                    if payment.invoice_id:
                        invoice = await self.db.get(Invoice, payment.invoice_id)
                        if invoice:
                            invoice.paid_amount += payment.amount
                            invoice.balance = invoice.total_amount - invoice.paid_amount
                            
                            if invoice.balance <= 0:
                                invoice.status = InvoiceStatus.PAID
                                invoice.paid_date = datetime.utcnow()

            await self.db.commit()

            return {
                "updated_payments": len(payment_ids),
                "new_status": new_status.value,
                "updated_by": updated_by
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to bulk update payment status: {e}")
            raise

    async def search_payments(
        self,
        pagination: PaginationParams,
        search_term: str,
        search_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Advanced payment search functionality."""
        if not search_fields:
            search_fields = ["payment_number", "reference_number", "mpesa_receipt_number", "notes"]

        search_term = f"%{search_term}%"
        conditions = []

        for field in search_fields:
            if hasattr(Payment, field):
                conditions.append(getattr(Payment, field).ilike(search_term))

        if not conditions:
            raise ValidationError("No valid search fields provided")

        query = select(Payment).where(or_(*conditions))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get payments with pagination
        query = query.order_by(desc(Payment.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        payments = result.scalars().all()

        return {
            "items": payments,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
            "search_term": search_term.strip('%'),
            "search_fields": search_fields
        }

    async def get_payment_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get payment summary with earnings visibility toggles."""
        if not start_date:
            start_date = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if not end_date:
            end_date = datetime.utcnow()

        # Daily earnings
        daily_result = await self.db.execute(
            select(
                func.date(Payment.payment_date).label('payment_date'),
                func.sum(Payment.amount).label('daily_total')
            )
            .where(
                and_(
                    Payment.payment_date >= start_date,
                    Payment.payment_date <= end_date,
                    Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.CHECKED])
                )
            )
            .group_by(func.date(Payment.payment_date))
            .order_by(func.date(Payment.payment_date).desc())
        )
        daily_earnings = [
            {"date": row.payment_date.isoformat(), "amount": float(row.daily_total or 0)}
            for row in daily_result
        ]

        # Weekly earnings
        weekly_result = await self.db.execute(
            select(func.sum(Payment.amount))
            .where(
                and_(
                    Payment.payment_date >= start_date - timedelta(days=7),
                    Payment.payment_date <= end_date,
                    Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.CHECKED])
                )
            )
        )
        weekly_total = weekly_result.scalar() or 0

        # Monthly earnings
        monthly_result = await self.db.execute(
            select(func.sum(Payment.amount))
            .where(
                and_(
                    Payment.payment_date >= start_date,
                    Payment.payment_date <= end_date,
                    Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.CHECKED])
                )
            )
        )
        monthly_total = monthly_result.scalar() or 0

        # Payment status breakdown
        status_result = await self.db.execute(
            select(
                Payment.status,
                func.count(Payment.id).label('count'),
                func.sum(Payment.amount).label('total_amount')
            )
            .where(
                and_(
                    Payment.created_at >= start_date,
                    Payment.created_at <= end_date
                )
            )
            .group_by(Payment.status)
        )
        
        status_breakdown = {}
        for row in status_result:
            status_breakdown[row.status.value] = {
                "count": row.count,
                "total_amount": float(row.total_amount or 0)
            }

        # Transaction cost tracking (simplified - 1% of total)
        transaction_cost = monthly_total * Decimal('0.01')

        return {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "earnings": {
                "daily": daily_earnings,
                "weekly_total": float(weekly_total),
                "monthly_total": float(monthly_total),
                "transaction_cost": float(transaction_cost)
            },
            "status_breakdown": status_breakdown,
            "verification_required": status_breakdown.get("unchecked", {}).get("count", 0)
        }

    async def get_payment_disbursement_tracking(
        self,
        pagination: PaginationParams,
        disbursement_method: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get payment disbursement tracking."""
        query = select(Payment).where(Payment.disbursement_method.isnot(None))

        # Apply filters
        if disbursement_method:
            query = query.where(Payment.disbursement_method == disbursement_method)
        if start_date:
            query = query.where(Payment.created_at >= start_date)
        if end_date:
            query = query.where(Payment.created_at <= end_date)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get payments with pagination
        query = query.order_by(desc(Payment.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        payments = result.scalars().all()

        # Calculate disbursement summary
        disbursement_methods = await self.db.execute(
            select(
                Payment.disbursement_method,
                func.count(Payment.id).label('count'),
                func.sum(Payment.amount).label('total_amount')
            )
            .where(Payment.disbursement_method.isnot(None))
            .group_by(Payment.disbursement_method)
        )
        
        disbursement_summary = {}
        for row in disbursement_methods:
            disbursement_summary[row.disbursement_method] = {
                "count": row.count,
                "total_amount": float(row.total_amount or 0)
            }

        return {
            "items": payments,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
            "disbursement_summary": disbursement_summary
        }

    async def update_payment_disbursement(
        self,
        payment_id: int,
        disbursement_method: str,
        disbursement_reference: str,
        updated_by: int
    ) -> bool:
        """Update payment disbursement information."""
        payment = await self.db.get(Payment, payment_id)
        if not payment:
            return False

        try:
            payment.disbursement_method = disbursement_method
            payment.disbursement_reference = disbursement_reference
            payment.updated_at = datetime.utcnow()

            await self.db.commit()

            self.logger.info(f"Updated disbursement for payment {payment.payment_number}")
            return True

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to update payment disbursement {payment_id}: {e}")
            return False

    async def generate_payment_report(
        self,
        start_date: datetime,
        end_date: datetime,
        include_details: bool = True
    ) -> Dict[str, Any]:
        """Generate comprehensive payment report."""
        # Get all payments in period
        result = await self.db.execute(
            select(Payment)
            .where(
                and_(
                    Payment.created_at >= start_date,
                    Payment.created_at <= end_date
                )
            )
            .order_by(Payment.created_at.desc())
        )
        payments = result.scalars().all()

        # Calculate summary metrics
        total_payments = len(payments)
        total_amount = sum(float(p.amount) for p in payments)
        verified_payments = len([p for p in payments if p.status == PaymentStatus.CHECKED])
        unverified_payments = len([p for p in payments if p.status == PaymentStatus.UNCHECKED])
        manual_payments = len([p for p in payments if p.is_manual_payment])

        # Group by payment method
        method_breakdown = {}
        for payment in payments:
            method = payment.payment_method.value
            if method not in method_breakdown:
                method_breakdown[method] = {"count": 0, "amount": 0}
            method_breakdown[method]["count"] += 1
            method_breakdown[method]["amount"] += float(payment.amount)

        # Group by status
        status_breakdown = {}
        for payment in payments:
            status = payment.status.value
            if status not in status_breakdown:
                status_breakdown[status] = {"count": 0, "amount": 0}
            status_breakdown[status]["count"] += 1
            status_breakdown[status]["amount"] += float(payment.amount)

        report = {
            "report_period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": (end_date - start_date).days
            },
            "summary": {
                "total_payments": total_payments,
                "total_amount": total_amount,
                "verified_payments": verified_payments,
                "unverified_payments": unverified_payments,
                "manual_payments": manual_payments,
                "verification_rate": round(verified_payments / total_payments * 100, 2) if total_payments > 0 else 0
            },
            "breakdown": {
                "by_method": method_breakdown,
                "by_status": status_breakdown
            },
            "generated_at": datetime.utcnow().isoformat()
        }

        if include_details:
            report["payment_details"] = [
                {
                    "id": p.id,
                    "payment_number": p.payment_number,
                    "amount": float(p.amount),
                    "status": p.status.value,
                    "method": p.payment_method.value,
                    "is_manual": p.is_manual_payment,
                    "created_at": p.created_at.isoformat(),
                    "verified_at": p.verified_at.isoformat() if p.verified_at else None
                }
                for p in payments
            ]

        return report

    # Helper methods
    def _generate_payment_number(self, prefix: str = "PAY") -> str:
        """Generate unique payment number."""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_part = ''.join(secrets.choice(string.digits) for _ in range(4))
        return f"{prefix}-{timestamp}-{random_part}"

    async def _update_invoice_payment_status(self, invoice_id: int) -> None:
        """Update invoice payment status based on payments."""
        invoice = await self.db.get(Invoice, invoice_id)
        if not invoice:
            return

        # Calculate total paid amount from verified payments
        result = await self.db.execute(
            select(func.sum(Payment.amount))
            .where(
                and_(
                    Payment.invoice_id == invoice_id,
                    Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.CHECKED])
                )
            )
        )
        total_paid = result.scalar() or 0

        # Update invoice
        invoice.paid_amount = total_paid
        invoice.balance = invoice.total_amount - total_paid

        if invoice.balance <= 0:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_date = datetime.utcnow()
        elif total_paid > 0:
            invoice.status = InvoiceStatus.PENDING  # Partially paid

        await self.db.commit()
