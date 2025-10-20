"""Support ticket management service."""

from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import (
    SupportTicket, 
    TicketMessage, 
    TicketStatus, 
    TicketPriority
)
from app.models.user import User
from app.api.deps import PaginationParams


class TicketService:
    """Support ticket management service."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_ticket_by_id(self, ticket_id: int) -> Optional[SupportTicket]:
        """Get ticket by ID."""
        return await self.db.get(SupportTicket, ticket_id)

    async def get_ticket_by_number(self, ticket_number: str) -> Optional[SupportTicket]:
        """Get ticket by ticket number."""
        result = await self.db.execute(
            select(SupportTicket).where(SupportTicket.ticket_number == ticket_number)
        )
        return result.scalar_one_or_none()

    async def get_tickets(
        self,
        pagination: PaginationParams,
        user_id: Optional[int] = None,
        assigned_to: Optional[int] = None,
        status: Optional[TicketStatus] = None,
        priority: Optional[TicketPriority] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all tickets with pagination and filters."""
        query = select(SupportTicket)

        # Apply filters
        if user_id:
            query = query.where(SupportTicket.user_id == user_id)
        if assigned_to:
            query = query.where(SupportTicket.assigned_to == assigned_to)
        if status:
            query = query.where(SupportTicket.status == status)
        if priority:
            query = query.where(SupportTicket.priority == priority)
        if category:
            query = query.where(SupportTicket.category == category)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (SupportTicket.subject.ilike(search_term))
                | (SupportTicket.description.ilike(search_term))
                | (SupportTicket.ticket_number.ilike(search_term))
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
        category: Optional[str] = None,
        priority: TicketPriority = TicketPriority.MEDIUM,
        tags: Optional[str] = None,
        attachments: Optional[str] = None,
    ) -> SupportTicket:
        """Create a new support ticket."""
        # Generate ticket number
        ticket_number = await self._generate_ticket_number()

        ticket = SupportTicket(
            user_id=user_id,
            ticket_number=ticket_number,
            subject=subject,
            description=description,
            category=category,
            priority=priority,
            tags=tags,
            attachments=attachments,
            status=TicketStatus.OPEN,
        )

        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)

        return ticket

    async def update_ticket(
        self, 
        ticket_id: int, 
        update_data: Dict[str, Any],
        updated_by: Optional[int] = None
    ) -> Optional[SupportTicket]:
        """Update ticket."""
        ticket = await self.get_ticket_by_id(ticket_id)
        if not ticket:
            return None

        old_status = ticket.status.value if ticket.status else None

        # Update fields
        for field, value in update_data.items():
            if hasattr(ticket, field) and value is not None:
                setattr(ticket, field, value)

        await self.db.commit()
        await self.db.refresh(ticket)

        # Log status change if applicable
        if old_status and ticket.status.value != old_status:
            await self._log_ticket_action(
                ticket_id,
                "status_changed",
                f"Status changed from {old_status} to {ticket.status.value}",
                updated_by
            )

        return ticket

    async def assign_ticket(
        self, 
        ticket_id: int, 
        assigned_to: int,
        assigned_by: Optional[int] = None
    ) -> Optional[SupportTicket]:
        """Assign ticket to user."""
        ticket = await self.get_ticket_by_id(ticket_id)
        if not ticket:
            return None

        # Verify assignee exists
        assignee = await self.db.get(User, assigned_to)
        if not assignee:
            raise ValueError("Assignee not found")

        ticket.assigned_to = assigned_to
        ticket.status = TicketStatus.IN_PROGRESS
        
        await self.db.commit()
        await self.db.refresh(ticket)

        await self._log_ticket_action(
            ticket_id,
            "assigned",
            f"Ticket assigned to {assignee.username}",
            assigned_by
        )

        return ticket

    async def resolve_ticket(
        self, 
        ticket_id: int, 
        resolution: str,
        resolved_by: Optional[int] = None
    ) -> Optional[SupportTicket]:
        """Resolve ticket."""
        ticket = await self.get_ticket_by_id(ticket_id)
        if not ticket:
            return None

        ticket.status = TicketStatus.RESOLVED
        ticket.resolution = resolution
        ticket.resolved_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(ticket)

        await self._log_ticket_action(
            ticket_id,
            "resolved",
            f"Ticket resolved: {resolution}",
            resolved_by
        )

        return ticket

    async def close_ticket(
        self, 
        ticket_id: int, 
        closed_by: Optional[int] = None
    ) -> Optional[SupportTicket]:
        """Close ticket."""
        ticket = await self.get_ticket_by_id(ticket_id)
        if not ticket:
            return None

        ticket.status = TicketStatus.CLOSED
        ticket.closed_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(ticket)

        await self._log_ticket_action(
            ticket_id,
            "closed",
            "Ticket closed",
            closed_by
        )

        return ticket

    async def cancel_ticket(
        self, 
        ticket_id: int, 
        cancelled_by: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Optional[SupportTicket]:
        """Cancel ticket."""
        ticket = await self.get_ticket_by_id(ticket_id)
        if not ticket:
            return None

        ticket.status = TicketStatus.CANCELLED
        ticket.closed_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(ticket)

        await self._log_ticket_action(
            ticket_id,
            "cancelled",
            f"Ticket cancelled. Reason: {reason or 'No reason provided'}",
            cancelled_by
        )

        return ticket

    async def add_ticket_message(
        self,
        ticket_id: int,
        user_id: int,
        message: str,
        is_internal: bool = False,
        attachments: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> TicketMessage:
        """Add message to ticket."""
        ticket_message = TicketMessage(
            ticket_id=ticket_id,
            user_id=user_id,
            message=message,
            is_internal=is_internal,
            attachments=attachments,
            ip_address=ip_address,
        )

        self.db.add(ticket_message)
        await self.db.commit()
        await self.db.refresh(ticket_message)

        # Update ticket status if it was closed/resolved
        ticket = await self.get_ticket_by_id(ticket_id)
        if ticket and ticket.status in [TicketStatus.CLOSED, TicketStatus.RESOLVED]:
            ticket.status = TicketStatus.IN_PROGRESS
            await self.db.commit()

        return ticket_message

    async def get_ticket_messages(
        self, 
        ticket_id: int, 
        include_internal: bool = False
    ) -> List[TicketMessage]:
        """Get messages for ticket."""
        query = select(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
        
        if not include_internal:
            query = query.where(TicketMessage.is_internal == False)
        
        query = query.order_by(TicketMessage.created_at.asc())
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_user_tickets(
        self, 
        user_id: int, 
        status: Optional[TicketStatus] = None
    ) -> List[SupportTicket]:
        """Get tickets for specific user."""
        query = select(SupportTicket).where(SupportTicket.user_id == user_id)
        
        if status:
            query = query.where(SupportTicket.status == status)
        
        query = query.order_by(SupportTicket.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_assigned_tickets(
        self, 
        user_id: int, 
        status: Optional[TicketStatus] = None
    ) -> List[SupportTicket]:
        """Get tickets assigned to specific user."""
        query = select(SupportTicket).where(SupportTicket.assigned_to == user_id)
        
        if status:
            query = query.where(SupportTicket.status == status)
        
        query = query.order_by(SupportTicket.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_open_tickets(self) -> List[SupportTicket]:
        """Get all open tickets."""
        result = await self.db.execute(
            select(SupportTicket).where(
                SupportTicket.status.in_([
                    TicketStatus.OPEN,
                    TicketStatus.IN_PROGRESS
                ])
            ).order_by(SupportTicket.priority.desc(), SupportTicket.created_at.asc())
        )
        return result.scalars().all()

    async def get_ticket_stats(self) -> Dict[str, Any]:
        """Get ticket statistics."""
        # Total tickets
        result = await self.db.execute(select(func.count(SupportTicket.id)))
        total_tickets = result.scalar() or 0

        # Open tickets
        result = await self.db.execute(
            select(func.count(SupportTicket.id)).where(SupportTicket.status == TicketStatus.OPEN)
        )
        open_tickets = result.scalar() or 0

        # In progress tickets
        result = await self.db.execute(
            select(func.count(SupportTicket.id)).where(SupportTicket.status == TicketStatus.IN_PROGRESS)
        )
        in_progress_tickets = result.scalar() or 0

        # Resolved tickets
        result = await self.db.execute(
            select(func.count(SupportTicket.id)).where(SupportTicket.status == TicketStatus.RESOLVED)
        )
        resolved_tickets = result.scalar() or 0

        # Closed tickets
        result = await self.db.execute(
            select(func.count(SupportTicket.id)).where(SupportTicket.status == TicketStatus.CLOSED)
        )
        closed_tickets = result.scalar() or 0

        # Average resolution time (in hours)
        result = await self.db.execute(
            select(func.avg(
                func.extract('epoch', SupportTicket.resolved_at - SupportTicket.created_at) / 3600
            )).where(SupportTicket.resolved_at.isnot(None))
        )
        avg_resolution_time = result.scalar() or 0

        return {
            "total_tickets": total_tickets,
            "open_tickets": open_tickets,
            "in_progress_tickets": in_progress_tickets,
            "resolved_tickets": resolved_tickets,
            "closed_tickets": closed_tickets,
            "avg_resolution_time_hours": round(avg_resolution_time, 2),
            "resolution_rate": (resolved_tickets + closed_tickets) / total_tickets * 100 if total_tickets > 0 else 0,
        }

    async def get_ticket_stats_by_priority(self) -> Dict[str, int]:
        """Get ticket statistics by priority."""
        result = await self.db.execute(
            select(SupportTicket.priority, func.count(SupportTicket.id))
            .group_by(SupportTicket.priority)
        )
        
        stats = {}
        for priority, count in result:
            stats[priority.value] = count
        
        return stats

    async def get_ticket_stats_by_category(self) -> Dict[str, int]:
        """Get ticket statistics by category."""
        result = await self.db.execute(
            select(SupportTicket.category, func.count(SupportTicket.id))
            .where(SupportTicket.category.isnot(None))
            .group_by(SupportTicket.category)
        )
        
        stats = {}
        for category, count in result:
            stats[category] = count
        
        return stats

    async def _generate_ticket_number(self) -> str:
        """Generate unique ticket number."""
        # Get current year and month
        now = datetime.utcnow()
        year_month = now.strftime("%Y%m")
        
        # Get count of tickets for this month
        result = await self.db.execute(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.ticket_number.like(f"TKT-{year_month}%")
            )
        )
        count = result.scalar() or 0
        
        # Generate ticket number
        ticket_number = f"TKT-{year_month}-{count + 1:04d}"
        return ticket_number

    async def _log_ticket_action(
        self,
        ticket_id: int,
        action: str,
        details: str,
        user_id: Optional[int] = None,
    ) -> None:
        """Log ticket action."""
        from app.models.notification import TicketMessage
        
        # Create a ticket message for the action log
        message = TicketMessage(
            ticket_id=ticket_id,
            message=f"[{action.upper()}] {details}",
            is_internal=True,
            user_id=user_id,
        )
        
        self.db.add(message)
        await self.db.commit()
