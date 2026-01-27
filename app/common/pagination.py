"""Pagination utilities for API responses.

This module provides standardized pagination for all list endpoints.
"""

from dataclasses import dataclass
from typing import Generic, List, Optional, Sequence, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters from query string.

    Attributes:
        page: Current page number (1-indexed).
        per_page: Number of items per page.
        sort_by: Field to sort by.
        sort_order: Sort direction ('asc' or 'desc').
    """

    page: int = 1
    per_page: int = 20
    sort_by: Optional[str] = None
    sort_order: str = "desc"

    @property
    def skip(self) -> int:
        """Calculate offset for database query."""
        return (self.page - 1) * self.per_page

    @property
    def limit(self) -> int:
        """Alias for per_page."""
        return self.per_page


def get_pagination_params(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    sort_by: Optional[str] = Query(None, description="Field to sort by"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order"),
) -> PaginationParams:
    """FastAPI dependency for pagination parameters.

    Usage:
        @router.get("/items")
        async def list_items(pagination: PaginationParams = Depends(get_pagination_params)):
            ...
    """
    return PaginationParams(
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


class PaginationMeta(BaseModel):
    """Pagination metadata for response."""

    page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class PaginatedResponse(BaseModel, Generic[T]):
    """Standardized paginated response.

    Attributes:
        success: Always True for successful responses.
        data: List of items for the current page.
        meta: Pagination metadata.
    """

    success: bool = True
    data: List[T]
    meta: PaginationMeta


@dataclass
class PaginationResult(Generic[T]):
    """Internal pagination result before serialization."""

    items: Sequence[T]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        """Calculate total number of pages."""
        if self.per_page <= 0:
            return 0
        return (self.total + self.per_page - 1) // self.per_page

    @property
    def has_next(self) -> bool:
        """Check if there's a next page."""
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        """Check if there's a previous page."""
        return self.page > 1

    def to_response(self) -> PaginatedResponse[T]:
        """Convert to PaginatedResponse model."""
        return PaginatedResponse(
            success=True,
            data=list(self.items),
            meta=PaginationMeta(
                page=self.page,
                per_page=self.per_page,
                total=self.total,
                total_pages=self.total_pages,
                has_next=self.has_next,
                has_prev=self.has_prev,
            ),
        )


async def paginate(
    session: AsyncSession,
    query: Select,
    params: PaginationParams,
) -> PaginationResult:
    """Apply pagination to a SQLAlchemy query.

    Args:
        session: Async database session.
        query: SQLAlchemy select query.
        params: Pagination parameters.

    Returns:
        PaginationResult with items and metadata.

    Example:
        query = select(User).where(User.is_active == True)
        result = await paginate(session, query, pagination_params)
        return result.to_response()
    """
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    paginated_query = query.offset(params.skip).limit(params.limit)
    result = await session.execute(paginated_query)
    items = result.scalars().all()

    return PaginationResult(
        items=items,
        total=total,
        page=params.page,
        per_page=params.per_page,
    )


async def paginate_list(
    items: Sequence[T],
    params: PaginationParams,
) -> PaginationResult[T]:
    """Apply pagination to an in-memory list.

    Args:
        items: Sequence of items to paginate.
        params: Pagination parameters.

    Returns:
        PaginationResult with sliced items and metadata.
    """
    total = len(items)
    start = params.skip
    end = start + params.limit
    page_items = items[start:end]

    return PaginationResult(
        items=page_items,
        total=total,
        page=params.page,
        per_page=params.per_page,
    )
