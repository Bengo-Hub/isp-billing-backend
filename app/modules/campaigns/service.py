"""Campaign service."""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignStatus, CampaignType
from app.api.deps import PaginationParams


class CampaignService:
    """Campaign service."""

    def __init__(self, db: AsyncSession, organization_id: int, user_id: int):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id

    async def get_by_id(self, campaign_id: int) -> Optional[Campaign]:
        """Get campaign by ID."""
        query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.organization_id == self.organization_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        pagination: PaginationParams,
        status: Optional[CampaignStatus] = None,
        campaign_type: Optional[CampaignType] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all campaigns with pagination and filters."""
        query = select(Campaign).where(Campaign.organization_id == self.organization_id)

        # Apply filters
        if status:
            query = query.where(Campaign.status == status)
        if campaign_type:
            query = query.where(Campaign.campaign_type == campaign_type)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    Campaign.name.ilike(search_term),
                    Campaign.notes.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get campaigns with pagination
        query = query.order_by(Campaign.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)

        result = await self.db.execute(query)
        campaigns = result.scalars().all()

        return {
            "items": campaigns,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_campaign(
        self,
        name: str,
        campaign_type: CampaignType,
        message_content: Optional[str] = None,
        email_subject: Optional[str] = None,
        email_content: Optional[str] = None,
        target_filters: Optional[str] = None,
        scheduled_date: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> Campaign:
        """Create a new campaign."""
        campaign = Campaign(
            organization_id=self.organization_id,
            name=name,
            campaign_type=campaign_type,
            status=CampaignStatus.DRAFT,
            message_content=message_content,
            email_subject=email_subject,
            email_content=email_content,
            target_filters=target_filters,
            scheduled_date=scheduled_date,
            created_by_user_id=self.user_id,
            notes=notes,
        )

        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def update_campaign(
        self,
        campaign_id: int,
        update_data: Dict[str, Any],
    ) -> Optional[Campaign]:
        """Update a campaign."""
        campaign = await self.get_by_id(campaign_id)
        if not campaign:
            return None

        # Only allow updates for draft campaigns
        if campaign.status not in [CampaignStatus.DRAFT, CampaignStatus.SCHEDULED]:
            raise ValueError("Can only update draft or scheduled campaigns")

        # Update fields
        for key, value in update_data.items():
            if value is not None and hasattr(campaign, key):
                setattr(campaign, key, value)

        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def delete_campaign(self, campaign_id: int) -> bool:
        """Delete a campaign."""
        campaign = await self.get_by_id(campaign_id)
        if not campaign:
            return False

        # Only allow deletion of draft campaigns
        if campaign.status != CampaignStatus.DRAFT:
            raise ValueError("Can only delete draft campaigns")

        await self.db.delete(campaign)
        await self.db.commit()
        return True

    async def pause_campaign(self, campaign_id: int) -> Optional[Campaign]:
        """Pause an active campaign."""
        campaign = await self.get_by_id(campaign_id)
        if not campaign:
            return None

        if campaign.status != CampaignStatus.ACTIVE:
            raise ValueError("Can only pause active campaigns")

        campaign.status = CampaignStatus.PAUSED
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def resume_campaign(self, campaign_id: int) -> Optional[Campaign]:
        """Resume a paused campaign."""
        campaign = await self.get_by_id(campaign_id)
        if not campaign:
            return None

        if campaign.status != CampaignStatus.PAUSED:
            raise ValueError("Can only resume paused campaigns")

        campaign.status = CampaignStatus.ACTIVE
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def get_analytics(self, campaign_id: int) -> Dict[str, Any]:
        """Get campaign analytics."""
        campaign = await self.get_by_id(campaign_id)
        if not campaign:
            return None

        # Calculate rates
        delivery_rate = (
            (campaign.delivered_count / campaign.sent_count * 100)
            if campaign.sent_count > 0 else 0.0
        )
        open_rate = (
            (campaign.opened_count / campaign.delivered_count * 100)
            if campaign.delivered_count > 0 else 0.0
        )
        click_rate = (
            (campaign.clicked_count / campaign.opened_count * 100)
            if campaign.opened_count > 0 else 0.0
        )

        return {
            "campaign_id": campaign.id,
            "recipients_count": campaign.recipients_count,
            "sent_count": campaign.sent_count,
            "delivered_count": campaign.delivered_count,
            "failed_count": campaign.failed_count,
            "opened_count": campaign.opened_count,
            "clicked_count": campaign.clicked_count,
            "delivery_rate": round(delivery_rate, 2),
            "open_rate": round(open_rate, 2),
            "click_rate": round(click_rate, 2),
        }
