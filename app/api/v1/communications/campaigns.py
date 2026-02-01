"""Campaigns API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.campaign import CampaignStatus, CampaignType
from app.schemas.campaign import (
    Campaign, CampaignCreate, CampaignUpdate, CampaignListResponse,
    CampaignAnalytics
)
from app.modules.campaigns import CampaignService

router = APIRouter()


@router.get("/", response_model=CampaignListResponse)
async def get_campaigns(
    pagination: PaginationParams = Depends(),
    status_filter: Optional[CampaignStatus] = Query(None, alias="status"),
    campaign_type: Optional[CampaignType] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignListResponse:
    """Get all campaigns with pagination and filters."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    result = await service.get_all(
        pagination=pagination,
        status=status_filter,
        campaign_type=campaign_type,
        search=search,
    )
    return CampaignListResponse(**result)


@router.post("/", response_model=Campaign, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    campaign_data: CampaignCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    """Create a new campaign."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    try:
        campaign = await service.create_campaign(
            name=campaign_data.name,
            campaign_type=campaign_data.campaign_type,
            message_content=campaign_data.message_content,
            email_subject=campaign_data.email_subject,
            email_content=campaign_data.email_content,
            target_filters=campaign_data.target_filters,
            scheduled_date=campaign_data.scheduled_date,
            notes=campaign_data.notes,
        )
        return campaign
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{campaign_id}", response_model=Campaign)
async def get_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    """Get campaign by ID."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    campaign = await service.get_by_id(campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    return campaign


@router.patch("/{campaign_id}", response_model=Campaign)
async def update_campaign(
    campaign_id: int,
    campaign_data: CampaignUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    """Update campaign."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    try:
        campaign = await service.update_campaign(
            campaign_id,
            campaign_data.dict(exclude_unset=True)
        )
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )
        return campaign
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete campaign."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    try:
        success = await service.delete_campaign(campaign_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{campaign_id}/pause", response_model=Campaign)
async def pause_campaign(
    campaign_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    """Pause campaign."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    try:
        campaign = await service.pause_campaign(campaign_id)
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )
        return campaign
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{campaign_id}/resume", response_model=Campaign)
async def resume_campaign(
    campaign_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    """Resume campaign."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    try:
        campaign = await service.resume_campaign(campaign_id)
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )
        return campaign
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{campaign_id}/analytics", response_model=CampaignAnalytics)
async def get_campaign_analytics(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignAnalytics:
    """Get campaign analytics."""
    service = CampaignService(db, current_user.organization_id, current_user.id)
    analytics = await service.get_analytics(campaign_id)
    if not analytics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    return CampaignAnalytics(**analytics)
