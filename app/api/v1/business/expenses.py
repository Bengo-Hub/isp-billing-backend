"""Expenses API endpoints."""

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.api.deps_org import get_org_id_for_query
from app.core.database import get_db
from app.models.user import User
from app.models.expense import ExpenseStatus, ExpenseCategory
from app.schemas.expense import (
    Expense, ExpenseCreate, ExpenseUpdate, ExpenseListResponse,
    ExpenseStats, ExpenseReject
)
from app.modules.expenses import ExpenseService

router = APIRouter()


@router.get("/", response_model=ExpenseListResponse)
async def get_expenses(
    pagination: PaginationParams = Depends(),
    status_filter: Optional[ExpenseStatus] = Query(None, alias="status"),
    category: Optional[ExpenseCategory] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExpenseListResponse:
    """Get all expenses with pagination and filters."""
    service = ExpenseService(db, org_id, current_user.id)
    result = await service.get_all(
        pagination=pagination,
        status=status_filter,
        category=category,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    return ExpenseListResponse(**result)


@router.post("/", response_model=Expense, status_code=status.HTTP_201_CREATED)
async def create_expense(
    expense_data: ExpenseCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    """Create a new expense."""
    service = ExpenseService(db, org_id, current_user.id)
    try:
        expense = await service.create_expense(
            date=expense_data.date,
            category=expense_data.category,
            description=expense_data.description,
            amount=expense_data.amount,
            currency=expense_data.currency,
            receipt_url=expense_data.receipt_url,
            notes=expense_data.notes,
        )
        return expense
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{expense_id}", response_model=Expense)
async def get_expense(
    expense_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    """Get expense by ID."""
    service = ExpenseService(db, org_id, current_user.id)
    expense = await service.get_by_id(expense_id)
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found"
        )
    return expense


@router.patch("/{expense_id}", response_model=Expense)
async def update_expense(
    expense_id: int,
    expense_data: ExpenseUpdate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    """Update expense."""
    service = ExpenseService(db, org_id, current_user.id)
    try:
        expense = await service.update_expense(
            expense_id,
            expense_data.dict(exclude_unset=True)
        )
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
        return expense
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete expense."""
    service = ExpenseService(db, org_id, current_user.id)
    try:
        success = await service.delete_expense(expense_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{expense_id}/approve", response_model=Expense)
async def approve_expense(
    expense_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    """Approve expense."""
    service = ExpenseService(db, org_id, current_user.id)
    try:
        expense = await service.approve_expense(expense_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
        return expense
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{expense_id}/reject", response_model=Expense)
async def reject_expense(
    expense_id: int,
    reject_data: ExpenseReject,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    """Reject expense."""
    service = ExpenseService(db, org_id, current_user.id)
    try:
        expense = await service.reject_expense(
            expense_id,
            reject_data.rejection_reason
        )
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
        return expense
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/stats/", response_model=ExpenseStats)
async def get_expense_stats(
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExpenseStats:
    """Get expense statistics."""
    service = ExpenseService(db, org_id, current_user.id)
    stats = await service.get_statistics()
    return ExpenseStats(**stats)
