"""Leads API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, PaginationParams
from app.api.deps_org import get_org_id_for_query
from app.core.database import get_db
from app.models.user import User
from app.models.lead import LeadStatus, LeadSource
from app.schemas.lead import (
    Lead, LeadCreate, LeadUpdate, LeadListResponse, LeadAssign
)
from app.modules.leads import LeadService

router = APIRouter()


@router.get("/", response_model=LeadListResponse)
async def get_leads(
    pagination: PaginationParams = Depends(),
    status_filter: Optional[LeadStatus] = Query(None, alias="status"),
    source: Optional[LeadSource] = Query(None),
    search: Optional[str] = Query(None),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadListResponse:
    """Get all leads with pagination and filters."""
    service = LeadService(db, org_id, current_user.id)
    result = await service.get_all(
        pagination=pagination,
        status=status_filter,
        source=source,
        search=search,
    )
    return LeadListResponse(**result)


@router.post("/", response_model=Lead, status_code=status.HTTP_201_CREATED)
async def create_lead(
    lead_data: LeadCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    """Create a new lead."""
    service = LeadService(db, org_id, current_user.id)
    try:
        lead = await service.create_lead(
            name=lead_data.name,
            email=lead_data.email,
            phone=lead_data.phone,
            company=lead_data.company,
            address=lead_data.address,
            city=lead_data.city,
            source=lead_data.source,
            notes=lead_data.notes,
            estimated_value=lead_data.estimated_value,
        )
        return lead
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{lead_id}", response_model=Lead)
async def get_lead(
    lead_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    """Get lead by ID."""
    service = LeadService(db, org_id, current_user.id)
    lead = await service.get_by_id(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )
    return lead


@router.patch("/{lead_id}", response_model=Lead)
async def update_lead(
    lead_id: int,
    lead_data: LeadUpdate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    """Update lead."""
    service = LeadService(db, org_id, current_user.id)
    try:
        lead = await service.update_lead(
            lead_id,
            lead_data.dict(exclude_unset=True)
        )
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        return lead
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete lead."""
    service = LeadService(db, org_id, current_user.id)
    try:
        success = await service.delete_lead(lead_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{lead_id}/assign", response_model=Lead)
async def assign_lead(
    lead_id: int,
    assign_data: LeadAssign,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    """Assign lead to a user."""
    service = LeadService(db, org_id, current_user.id)
    try:
        lead = await service.assign_lead(lead_id, assign_data.assigned_to_user_id)
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        return lead
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{lead_id}/convert", response_model=Lead)
async def convert_lead(
    lead_id: int,
    converted_to_user_id: Optional[int] = Query(None, description="Customer user ID (optional; lead is marked converted even if not linked)"),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    """Convert lead to customer."""
    service = LeadService(db, org_id, current_user.id)
    try:
        lead = await service.convert_lead(lead_id, converted_to_user_id)
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        return lead
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
