"""Expense tracking service."""

from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expense import Expense, ExpenseStatus, ExpenseCategory
from app.api.deps import PaginationParams


class ExpenseService:
    """Expense tracking service."""

    def __init__(self, db: AsyncSession, organization_id: int, user_id: int):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id

    async def get_by_id(self, expense_id: int) -> Optional[Expense]:
        """Get expense by ID."""
        query = select(Expense).where(
            and_(
                Expense.id == expense_id,
                Expense.organization_id == self.organization_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        pagination: PaginationParams,
        status: Optional[ExpenseStatus] = None,
        category: Optional[ExpenseCategory] = None,
        search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Get all expenses with pagination and filters."""
        query = select(Expense).where(Expense.organization_id == self.organization_id)

        # Apply filters
        if status:
            query = query.where(Expense.status == status)
        if category:
            query = query.where(Expense.category == category)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    Expense.description.ilike(search_term),
                    Expense.notes.ilike(search_term)
                )
            )
        if date_from:
            query = query.where(Expense.date >= date_from)
        if date_to:
            query = query.where(Expense.date <= date_to)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get expenses with pagination
        query = query.order_by(Expense.date.desc(), Expense.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)

        result = await self.db.execute(query)
        expenses = result.scalars().all()

        return {
            "items": expenses,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_expense(
        self,
        date: date,
        category: ExpenseCategory,
        description: str,
        amount: Decimal,
        currency: str = "KES",
        receipt_url: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Expense:
        """Create a new expense."""
        expense = Expense(
            organization_id=self.organization_id,
            date=date,
            category=category,
            description=description,
            amount=amount,
            currency=currency,
            receipt_url=receipt_url,
            added_by_user_id=self.user_id,
            status=ExpenseStatus.PENDING,
            notes=notes,
        )

        self.db.add(expense)
        await self.db.commit()
        await self.db.refresh(expense)
        return expense

    async def update_expense(
        self,
        expense_id: int,
        update_data: Dict[str, Any],
    ) -> Optional[Expense]:
        """Update an expense."""
        expense = await self.get_by_id(expense_id)
        if not expense:
            return None

        # Only allow updates for pending expenses
        if expense.status != ExpenseStatus.PENDING:
            raise ValueError("Can only update pending expenses")

        # Update fields
        for key, value in update_data.items():
            if value is not None and hasattr(expense, key):
                setattr(expense, key, value)

        await self.db.commit()
        await self.db.refresh(expense)
        return expense

    async def delete_expense(self, expense_id: int) -> bool:
        """Delete an expense."""
        expense = await self.get_by_id(expense_id)
        if not expense:
            return False

        # Only allow deletion of pending expenses
        if expense.status != ExpenseStatus.PENDING:
            raise ValueError("Can only delete pending expenses")

        await self.db.delete(expense)
        await self.db.commit()
        return True

    async def approve_expense(self, expense_id: int) -> Optional[Expense]:
        """Approve an expense."""
        expense = await self.get_by_id(expense_id)
        if not expense:
            return None

        if expense.status != ExpenseStatus.PENDING:
            raise ValueError("Can only approve pending expenses")

        expense.status = ExpenseStatus.APPROVED
        expense.approved_by_user_id = self.user_id
        expense.approved_at = datetime.utcnow()
        expense.rejection_reason = None

        await self.db.commit()
        await self.db.refresh(expense)
        return expense

    async def reject_expense(
        self,
        expense_id: int,
        rejection_reason: str
    ) -> Optional[Expense]:
        """Reject an expense."""
        expense = await self.get_by_id(expense_id)
        if not expense:
            return None

        if expense.status != ExpenseStatus.PENDING:
            raise ValueError("Can only reject pending expenses")

        expense.status = ExpenseStatus.REJECTED
        expense.approved_by_user_id = self.user_id
        expense.approved_at = datetime.utcnow()
        expense.rejection_reason = rejection_reason

        await self.db.commit()
        await self.db.refresh(expense)
        return expense

    async def get_statistics(self) -> Dict[str, Any]:
        """Get expense statistics."""
        now = datetime.utcnow()
        today = now.date()
        month_start = today.replace(day=1)

        # Total expenses count and amount
        total_query = select(
            func.count(Expense.id),
            func.coalesce(func.sum(Expense.amount), 0)
        ).where(
            and_(
                Expense.organization_id == self.organization_id,
                Expense.status == ExpenseStatus.APPROVED
            )
        )
        total_result = await self.db.execute(total_query)
        total_count, total_amount = total_result.first()

        # Count by status
        approved_query = select(func.count()).where(
            and_(
                Expense.organization_id == self.organization_id,
                Expense.status == ExpenseStatus.APPROVED
            )
        )
        approved_result = await self.db.execute(approved_query)
        approved_count = approved_result.scalar()

        pending_query = select(func.count()).where(
            and_(
                Expense.organization_id == self.organization_id,
                Expense.status == ExpenseStatus.PENDING
            )
        )
        pending_result = await self.db.execute(pending_query)
        pending_count = pending_result.scalar()

        rejected_query = select(func.count()).where(
            and_(
                Expense.organization_id == self.organization_id,
                Expense.status == ExpenseStatus.REJECTED
            )
        )
        rejected_result = await self.db.execute(rejected_query)
        rejected_count = rejected_result.scalar()

        # Daily expenses (today)
        daily_query = select(func.coalesce(func.sum(Expense.amount), 0)).where(
            and_(
                Expense.organization_id == self.organization_id,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.date == today
            )
        )
        daily_result = await self.db.execute(daily_query)
        daily_expenses = daily_result.scalar()

        # Monthly expenses
        monthly_query = select(func.coalesce(func.sum(Expense.amount), 0)).where(
            and_(
                Expense.organization_id == self.organization_id,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.date >= month_start
            )
        )
        monthly_result = await self.db.execute(monthly_query)
        monthly_expenses = monthly_result.scalar()

        # Expenses by category
        category_query = select(
            Expense.category,
            func.sum(Expense.amount)
        ).where(
            and_(
                Expense.organization_id == self.organization_id,
                Expense.status == ExpenseStatus.APPROVED
            )
        ).group_by(Expense.category)

        category_result = await self.db.execute(category_query)
        by_category = {str(cat): float(amt) for cat, amt in category_result}

        return {
            "total_expenses": total_count or 0,
            "approved_expenses": approved_count or 0,
            "pending_expenses": pending_count or 0,
            "rejected_expenses": rejected_count or 0,
            "total_amount": float(total_amount or 0),
            "daily_expenses": float(daily_expenses or 0),
            "monthly_expenses": float(monthly_expenses or 0),
            "by_category": by_category,
        }
