"""Ticket service."""

from datetime import datetime
from typing import Any, Dict, Optional
import secrets

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import SupportTicket, TicketMessage, TicketStatus, TicketPriority
from app.api.deps import PaginationParams


class TicketService:
    """Ticket service."""

    def __init__(self, db: AsyncSession, organization_id: int, user_id: int):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id

    async def _generate_ticket_number(self) -> str:
        """Generate unique ticket number."""
        # Generate ticket number like TKT-20250201-ABC123
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        random_suffix = secrets.token_hex(3).upper()
        return f"TKT-{timestamp}-{random_suffix}"

    async def get_by_id(self, ticket_id: int) -> Optional[SupportTicket]:
        """Get ticket by ID."""
        query = select(SupportTicket).where(
            and_(
                SupportTicket.id == ticket_id,
                SupportTicket.organization_id == self.organization_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        pagination: PaginationParams,
        status: Optional[TicketStatus] = None,
        priority: Optional[TicketPriority] = None,
        user_id: Optional[int] = None,
        assigned_to: Optional[int] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all tickets with pagination and filters."""
        query = select(SupportTicket).where(SupportTicket.organization_id == self.organization_id)

        # Apply filters
        if status:
            query = query.where(SupportTicket.status == status)
        if priority:
            query = query.where(SupportTicket.priority == priority)
        if user_id:
            query = query.where(SupportTicket.user_id == user_id)
        if assigned_to:
            query = query.where(SupportTicket.assigned_to == assigned_to)
        if category:
            query = query.where(SupportTicket.category.ilike(f"%{category}%"))
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    SupportTicket.ticket_number.ilike(search_term),
                    SupportTicket.subject.ilike(search_term),
                    SupportTicket.description.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get tickets with pagination
        query = query.order_by(SupportTicket.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)

        result = await self.db.execute(query)
        tickets = result.scalars().all()

        return {
            "tickets": tickets,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def create_ticket(
        self,
        user_id: int,
        subject: str,
        description: str,
        priority: TicketPriority = TicketPriority.MEDIUM,
        category: Optional[str] = None,
        tags: Optional[str] = None,
        attachments: Optional[str] = None,
    ) -> SupportTicket:
        """Create a new support ticket."""
        ticket_number = await self._generate_ticket_number()

        ticket = SupportTicket(
            organization_id=self.organization_id,
            user_id=user_id,
            ticket_number=ticket_number,
            subject=subject,
            description=description,
            status=TicketStatus.OPEN,
            priority=priority,
            category=category,
            tags=tags,
            attachments=attachments,
        )

        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def update_ticket(
        self,
        ticket_id: int,
        update_data: Dict[str, Any],
    ) -> Optional[SupportTicket]:
        """Update a ticket."""
        ticket = await self.get_by_id(ticket_id)
        if not ticket:
            return None

        # Update fields
        for key, value in update_data.items():
            if value is not None and hasattr(ticket, key):
                setattr(ticket, key, value)

        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def assign_ticket(
        self,
        ticket_id: int,
        assigned_to: int
    ) -> Optional[SupportTicket]:
        """Assign a ticket to a user."""
        ticket = await self.get_by_id(ticket_id)
        if not ticket:
            return None

        ticket.assigned_to = assigned_to
        if ticket.status == TicketStatus.OPEN:
            ticket.status = TicketStatus.IN_PROGRESS

        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def add_message(
        self,
        ticket_id: int,
        message: str,
        is_internal: bool = False,
        attachments: Optional[str] = None,
    ) -> Optional[TicketMessage]:
        """Add a message to a ticket."""
        ticket = await self.get_by_id(ticket_id)
        if not ticket:
            return None

        ticket_message = TicketMessage(
            ticket_id=ticket_id,
            user_id=self.user_id,
            message=message,
            is_internal=is_internal,
            attachments=attachments,
        )

        self.db.add(ticket_message)
        await self.db.commit()
        await self.db.refresh(ticket_message)
        return ticket_message

    async def resolve_ticket(
        self,
        ticket_id: int,
        resolution: str
    ) -> Optional[SupportTicket]:
        """Resolve a ticket."""
        ticket = await self.get_by_id(ticket_id)
        if not ticket:
            return None

        if ticket.status == TicketStatus.CLOSED:
            raise ValueError("Cannot resolve a closed ticket")

        ticket.status = TicketStatus.RESOLVED
        ticket.resolution = resolution
        ticket.resolved_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def close_ticket(self, ticket_id: int) -> Optional[SupportTicket]:
        """Close a ticket."""
        ticket = await self.get_by_id(ticket_id)
        if not ticket:
            return None

        ticket.status = TicketStatus.CLOSED
        ticket.closed_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def get_statistics(self) -> Dict[str, Any]:
        """Get ticket statistics."""
        # Total tickets
        total_query = select(func.count()).where(
            SupportTicket.organization_id == self.organization_id
        )
        total_result = await self.db.execute(total_query)
        total_tickets = total_result.scalar()

        # Count by status
        open_query = select(func.count()).where(
            and_(
                SupportTicket.organization_id == self.organization_id,
                SupportTicket.status == TicketStatus.OPEN
            )
        )
        open_result = await self.db.execute(open_query)
        open_tickets = open_result.scalar()

        in_progress_query = select(func.count()).where(
            and_(
                SupportTicket.organization_id == self.organization_id,
                SupportTicket.status == TicketStatus.IN_PROGRESS
            )
        )
        in_progress_result = await self.db.execute(in_progress_query)
        in_progress_tickets = in_progress_result.scalar()

        resolved_query = select(func.count()).where(
            and_(
                SupportTicket.organization_id == self.organization_id,
                SupportTicket.status == TicketStatus.RESOLVED
            )
        )
        resolved_result = await self.db.execute(resolved_query)
        resolved_tickets = resolved_result.scalar()

        closed_query = select(func.count()).where(
            and_(
                SupportTicket.organization_id == self.organization_id,
                SupportTicket.status == TicketStatus.CLOSED
            )
        )
        closed_result = await self.db.execute(closed_query)
        closed_tickets = closed_result.scalar()

        # Urgent tickets
        urgent_query = select(func.count()).where(
            and_(
                SupportTicket.organization_id == self.organization_id,
                SupportTicket.priority == TicketPriority.URGENT,
                SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS])
            )
        )
        urgent_result = await self.db.execute(urgent_query)
        urgent_tickets = urgent_result.scalar()

        return {
            "total_tickets": total_tickets or 0,
            "open_tickets": open_tickets or 0,
            "in_progress_tickets": in_progress_tickets or 0,
            "resolved_tickets": resolved_tickets or 0,
            "closed_tickets": closed_tickets or 0,
            "urgent_tickets": urgent_tickets or 0,
        }
