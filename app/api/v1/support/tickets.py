"""Support Tickets API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.api.deps_org import get_org_id_for_query
from app.core.database import get_db
from app.models.user import User
from app.models.notification import TicketStatus, TicketPriority
from app.schemas.ticket import (
    SupportTicket, SupportTicketCreate, SupportTicketUpdate,
    SupportTicketList, TicketMessageCreate, TicketMessage,
    TicketAssignmentRequest, TicketResolutionRequest, TicketStats
)
from app.modules.tickets import TicketService

router = APIRouter()


@router.get("/", response_model=SupportTicketList)
async def get_tickets(
    pagination: PaginationParams = Depends(),
    status_filter: Optional[TicketStatus] = Query(None, alias="status"),
    priority: Optional[TicketPriority] = Query(None),
    user_id: Optional[int] = Query(None),
    assigned_to: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportTicketList:
    """Get all tickets with pagination and filters."""
    service = TicketService(db, org_id, current_user.id)
    result = await service.get_all(
        pagination=pagination,
        status=status_filter,
        priority=priority,
        user_id=user_id,
        assigned_to=assigned_to,
        category=category,
        search=search,
    )
    return SupportTicketList(**result)


@router.post("/", response_model=SupportTicket, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    ticket_data: SupportTicketCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Create a new support ticket."""
    service = TicketService(db, org_id, current_user.id)
    try:
        ticket = await service.create_ticket(
            user_id=ticket_data.user_id,
            subject=ticket_data.subject,
            description=ticket_data.description,
            priority=ticket_data.priority,
            category=ticket_data.category,
            tags=ticket_data.tags,
            attachments=ticket_data.attachments,
        )
        return ticket
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{ticket_id}", response_model=SupportTicket)
async def get_ticket(
    ticket_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Get ticket by ID."""
    service = TicketService(db, org_id, current_user.id)
    ticket = await service.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    return ticket


@router.patch("/{ticket_id}", response_model=SupportTicket)
async def update_ticket(
    ticket_id: int,
    ticket_data: SupportTicketUpdate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Update ticket."""
    service = TicketService(db, org_id, current_user.id)
    try:
        ticket = await service.update_ticket(
            ticket_id,
            ticket_data.dict(exclude_unset=True)
        )
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )
        return ticket
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{ticket_id}/assign", response_model=SupportTicket)
async def assign_ticket(
    ticket_id: int,
    assignment_data: TicketAssignmentRequest,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Assign ticket to a user."""
    service = TicketService(db, org_id, current_user.id)
    try:
        ticket = await service.assign_ticket(ticket_id, assignment_data.assigned_to)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )
        return ticket
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{ticket_id}/messages", response_model=TicketMessage, status_code=status.HTTP_201_CREATED)
async def add_ticket_message(
    ticket_id: int,
    message_data: TicketMessageCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TicketMessage:
    """Add a message to a ticket."""
    service = TicketService(db, org_id, current_user.id)
    try:
        message = await service.add_message(
            ticket_id,
            message_data.message,
            message_data.is_internal,
            message_data.attachments,
        )
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )
        return message
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{ticket_id}/resolve", response_model=SupportTicket)
async def resolve_ticket(
    ticket_id: int,
    resolution_data: TicketResolutionRequest,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Resolve a ticket."""
    service = TicketService(db, org_id, current_user.id)
    try:
        ticket = await service.resolve_ticket(ticket_id, resolution_data.resolution)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )
        return ticket
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{ticket_id}/close", response_model=SupportTicket)
async def close_ticket(
    ticket_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Close a ticket."""
    service = TicketService(db, org_id, current_user.id)
    try:
        ticket = await service.close_ticket(ticket_id)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )
        return ticket
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/stats/", response_model=TicketStats)
async def get_ticket_stats(
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TicketStats:
    """Get ticket statistics."""
    service = TicketService(db, org_id, current_user.id)
    stats = await service.get_statistics()
    return TicketStats(**stats)
