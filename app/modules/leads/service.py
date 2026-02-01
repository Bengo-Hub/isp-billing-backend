"""Lead service."""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus, LeadSource
from app.api.deps import PaginationParams


class LeadService:
    """Lead service."""

    def __init__(self, db: AsyncSession, organization_id: int, user_id: int):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id

    async def get_by_id(self, lead_id: int) -> Optional[Lead]:
        """Get lead by ID."""
        query = select(Lead).where(
            and_(
                Lead.id == lead_id,
                Lead.organization_id == self.organization_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        pagination: PaginationParams,
        status: Optional[LeadStatus] = None,
        source: Optional[LeadSource] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all leads with pagination and filters."""
        query = select(Lead).where(Lead.organization_id == self.organization_id)

        # Apply filters
        if status:
            query = query.where(Lead.status == status)
        if source:
            query = query.where(Lead.source == source)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    Lead.name.ilike(search_term),
                    Lead.email.ilike(search_term),
                    Lead.phone.ilike(search_term),
                    Lead.company.ilike(search_term),
                    Lead.notes.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get leads with pagination
        query = query.order_by(Lead.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)

        result = await self.db.execute(query)
        leads = result.scalars().all()

        return {
            "items": leads,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_lead(
        self,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        company: Optional[str] = None,
        address: Optional[str] = None,
        city: Optional[str] = None,
        source: Optional[LeadSource] = None,
        notes: Optional[str] = None,
        estimated_value: Optional[int] = None,
    ) -> Lead:
        """Create a new lead."""
        lead = Lead(
            organization_id=self.organization_id,
            name=name,
            email=email,
            phone=phone,
            company=company,
            address=address,
            city=city,
            status=LeadStatus.NEW,
            source=source,
            notes=notes,
            estimated_value=estimated_value,
            created_by_user_id=self.user_id,
        )

        self.db.add(lead)
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def update_lead(
        self,
        lead_id: int,
        update_data: Dict[str, Any],
    ) -> Optional[Lead]:
        """Update a lead."""
        lead = await self.get_by_id(lead_id)
        if not lead:
            return None

        # Don't allow updates to converted leads
        if lead.status == LeadStatus.CONVERTED:
            raise ValueError("Cannot update converted leads")

        # Update fields
        for key, value in update_data.items():
            if value is not None and hasattr(lead, key):
                setattr(lead, key, value)

        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def delete_lead(self, lead_id: int) -> bool:
        """Delete a lead."""
        lead = await self.get_by_id(lead_id)
        if not lead:
            return False

        # Don't allow deletion of converted leads
        if lead.status == LeadStatus.CONVERTED:
            raise ValueError("Cannot delete converted leads")

        await self.db.delete(lead)
        await self.db.commit()
        return True

    async def assign_lead(
        self,
        lead_id: int,
        assigned_to_user_id: int
    ) -> Optional[Lead]:
        """Assign a lead to a user."""
        lead = await self.get_by_id(lead_id)
        if not lead:
            return None

        lead.assigned_to_user_id = assigned_to_user_id
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def convert_lead(
        self,
        lead_id: int,
        converted_to_user_id: int
    ) -> Optional[Lead]:
        """Convert a lead to a customer."""
        lead = await self.get_by_id(lead_id)
        if not lead:
            return None

        if lead.status == LeadStatus.CONVERTED:
            raise ValueError("Lead is already converted")

        lead.status = LeadStatus.CONVERTED
        lead.converted_to_user_id = converted_to_user_id
        lead.converted_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(lead)
        return lead
