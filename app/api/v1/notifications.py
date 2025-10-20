"""Notifications and Support Tickets API endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_technician_or_admin, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.notification import NotificationType, TicketStatus, TicketPriority
from app.schemas.notification import (
    Notification, NotificationCreate, NotificationUpdate, NotificationList,
    NotificationTemplate, NotificationTemplateCreate, NotificationTemplateUpdate,
    EmailNotificationRequest, SMSNotificationRequest, NotificationStats
)
from app.schemas.ticket import (
    SupportTicket, SupportTicketCreate, SupportTicketUpdate, SupportTicketList,
    SupportTicketFilter, TicketMessage, TicketMessageCreate, TicketMessageUpdate,
    TicketAssignmentRequest, TicketResolutionRequest, TicketCloseRequest, TicketCancelRequest,
    TicketStats, TicketStatsByPriority, TicketStatsByCategory, TicketDashboard, TicketSearchRequest
)
from app.services.notification_service import NotificationService
from app.services.ticket_service import TicketService

router = APIRouter()

# ==================== NOTIFICATIONS ====================

@router.get("/", response_model=NotificationList)
async def get_notifications(
    pagination: PaginationParams = Depends(),
    notification_type: Optional[NotificationType] = Query(None),
    is_read: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationList:
    """Get user notifications."""
    service = NotificationService(db)
    result = await service.get_user_notifications(
        user_id=current_user.id,
        pagination=pagination,
        notification_type=notification_type,
        is_read=is_read,
    )
    return NotificationList(**result)


@router.get("/{notification_id}", response_model=Notification)
async def get_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Notification:
    """Get notification by ID."""
    service = NotificationService(db)
    notification = await service.get_notification_by_id(notification_id)
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    # Users can only view their own notifications
    if notification.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this notification"
        )
    
    return notification


@router.patch("/{notification_id}/read", response_model=Dict[str, str])
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Mark notification as read."""
    service = NotificationService(db)
    success = await service.mark_notification_read(notification_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    return {"message": "Notification marked as read"}


@router.patch("/{notification_id}/unread", response_model=Dict[str, str])
async def mark_notification_unread(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Mark notification as unread."""
    service = NotificationService(db)
    success = await service.mark_notification_unread(notification_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    return {"message": "Notification marked as unread"}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete notification."""
    service = NotificationService(db)
    success = await service.delete_notification(notification_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )


@router.post("/", response_model=Notification, status_code=status.HTTP_201_CREATED)
async def create_notification(
    notification_data: NotificationCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Notification:
    """Create a new notification."""
    service = NotificationService(db)
    notification = await service.create_notification(
        user_id=notification_data.user_id,
        title=notification_data.title,
        message=notification_data.message,
        notification_type=notification_data.notification_type,
        priority=notification_data.priority,
        data=notification_data.data,
    )
    return notification


@router.post("/email", response_model=Dict[str, str])
async def send_email(
    email_data: EmailNotificationRequest,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Send custom email notification."""
    service = NotificationService(db)
    result = await service.send_email_notification(
        to_email=email_data.to_email,
        subject=email_data.subject,
        body=email_data.body,
        is_html=email_data.is_html
    )
    
    if result["status"] == "success":
        return {"message": "Email sent successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"]
        )


@router.post("/sms", response_model=Dict[str, str])
async def send_sms(
    sms_data: SMSNotificationRequest,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Send SMS notification."""
    service = NotificationService(db)
    result = await service.send_sms_notification(
        to_phone=sms_data.to_phone,
        message=sms_data.message
    )
    
    if result["status"] == "success":
        return {"message": "SMS sent successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"]
        )


# ==================== SUPPORT TICKETS ====================

@router.get("/tickets", response_model=SupportTicketList)
async def get_tickets(
    pagination: PaginationParams = Depends(),
    user_id: Optional[int] = Query(None),
    assigned_to: Optional[int] = Query(None),
    status: Optional[TicketStatus] = Query(None),
    priority: Optional[TicketPriority] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportTicketList:
    """Get all support tickets with pagination and filters."""
    # Users can only view their own tickets unless they're admin/technician
    if current_user.role not in ["admin", "technician"] and user_id and user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's tickets"
        )
    
    # Non-admin/technician users can only view their own tickets
    if current_user.role not in ["admin", "technician"]:
        user_id = current_user.id
    
    service = TicketService(db)
    result = await service.get_tickets(
        pagination=pagination,
        user_id=user_id,
        assigned_to=assigned_to,
        status=status,
        priority=priority,
        category=category,
        search=search,
    )
    return SupportTicketList(**result)


@router.post("/tickets", response_model=SupportTicket, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    ticket_data: SupportTicketCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Create a new support ticket."""
    service = TicketService(db)
    ticket = await service.create_ticket(
        user_id=current_user.id,
        subject=ticket_data.subject,
        description=ticket_data.description,
        category=ticket_data.category,
        priority=ticket_data.priority,
        tags=ticket_data.tags,
        attachments=ticket_data.attachments,
    )
    return ticket


@router.get("/tickets/{ticket_id}", response_model=SupportTicket)
async def get_ticket(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Get ticket by ID."""
    service = TicketService(db)
    ticket = await service.get_ticket_by_id(ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    
    # Users can only view their own tickets unless they're admin/technician
    if current_user.role not in ["admin", "technician"] and ticket.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this ticket"
        )
    
    return ticket


@router.patch("/tickets/{ticket_id}", response_model=SupportTicket)
async def update_ticket(
    ticket_id: int,
    ticket_data: SupportTicketUpdate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Update ticket."""
    service = TicketService(db)
    ticket = await service.update_ticket(
        ticket_id, 
        ticket_data.dict(exclude_unset=True),
        current_user.id
    )
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    return ticket


@router.post("/tickets/{ticket_id}/assign", response_model=SupportTicket)
async def assign_ticket(
    ticket_id: int,
    assignment_data: TicketAssignmentRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Assign ticket to user."""
    service = TicketService(db)
    ticket = await service.assign_ticket(
        ticket_id, 
        assignment_data.assigned_to,
        current_user.id
    )
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    return ticket


@router.post("/tickets/{ticket_id}/resolve", response_model=SupportTicket)
async def resolve_ticket(
    ticket_id: int,
    resolution_data: TicketResolutionRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Resolve ticket."""
    service = TicketService(db)
    ticket = await service.resolve_ticket(
        ticket_id, 
        resolution_data.resolution,
        current_user.id
    )
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    return ticket


@router.post("/tickets/{ticket_id}/close", response_model=SupportTicket)
async def close_ticket(
    ticket_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Close ticket."""
    service = TicketService(db)
    ticket = await service.close_ticket(ticket_id, current_user.id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    return ticket


@router.post("/tickets/{ticket_id}/cancel", response_model=SupportTicket)
async def cancel_ticket(
    ticket_id: int,
    cancel_data: TicketCancelRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SupportTicket:
    """Cancel ticket."""
    service = TicketService(db)
    ticket = await service.cancel_ticket(
        ticket_id, 
        current_user.id,
        cancel_data.reason
    )
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    return ticket


@router.get("/tickets/{ticket_id}/messages", response_model=List[TicketMessage])
async def get_ticket_messages(
    ticket_id: int,
    include_internal: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[TicketMessage]:
    """Get messages for ticket."""
    service = TicketService(db)
    # Check if user has access to ticket
    ticket = await service.get_ticket_by_id(ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    
    if current_user.role not in ["admin", "technician"] and ticket.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this ticket's messages"
        )
    
    messages = await service.get_ticket_messages(ticket_id, include_internal)
    return messages


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessage, status_code=status.HTTP_201_CREATED)
async def add_ticket_message(
    ticket_id: int,
    message_data: TicketMessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TicketMessage:
    """Add message to ticket."""
    service = TicketService(db)
    # Check if user has access to ticket
    ticket = await service.get_ticket_by_id(ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )
    
    if current_user.role not in ["admin", "technician"] and ticket.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to add messages to this ticket"
        )
    
    message = await service.add_ticket_message(
        ticket_id=ticket_id,
        user_id=current_user.id,
        message=message_data.message,
        is_internal=message_data.is_internal,
        attachments=message_data.attachments,
    )
    return message


@router.get("/tickets/user/{user_id}", response_model=List[SupportTicket])
async def get_user_tickets(
    user_id: int,
    status: Optional[TicketStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SupportTicket]:
    """Get tickets for specific user."""
    # Users can only view their own tickets unless they're admin/technician
    if current_user.role not in ["admin", "technician"] and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's tickets"
        )
    
    service = TicketService(db)
    tickets = await service.get_user_tickets(user_id, status)
    return tickets


@router.get("/tickets/assigned/{user_id}", response_model=List[SupportTicket])
async def get_assigned_tickets(
    user_id: int,
    status: Optional[TicketStatus] = Query(None),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[SupportTicket]:
    """Get tickets assigned to specific user."""
    service = TicketService(db)
    tickets = await service.get_assigned_tickets(user_id, status)
    return tickets


@router.get("/tickets/open", response_model=List[SupportTicket])
async def get_open_tickets(
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[SupportTicket]:
    """Get all open tickets."""
    service = TicketService(db)
    tickets = await service.get_open_tickets()
    return tickets


@router.get("/tickets/stats", response_model=TicketStats)
async def get_ticket_stats(
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> TicketStats:
    """Get ticket statistics."""
    service = TicketService(db)
    stats = await service.get_ticket_stats()
    return TicketStats(**stats)


@router.get("/tickets/stats/priority", response_model=TicketStatsByPriority)
async def get_ticket_stats_by_priority(
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> TicketStatsByPriority:
    """Get ticket statistics by priority."""
    service = TicketService(db)
    stats = await service.get_ticket_stats_by_priority()
    return TicketStatsByPriority(**stats)


@router.get("/tickets/stats/category", response_model=TicketStatsByCategory)
async def get_ticket_stats_by_category(
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> TicketStatsByCategory:
    """Get ticket statistics by category."""
    service = TicketService(db)
    stats = await service.get_ticket_stats_by_category()
    return TicketStatsByCategory(**stats)


@router.get("/tickets/dashboard", response_model=TicketDashboard)
async def get_ticket_dashboard(
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> TicketDashboard:
    """Get ticket dashboard data."""
    service = TicketService(db)
    stats = await service.get_ticket_stats()
    stats_by_priority = await service.get_ticket_stats_by_priority()
    stats_by_category = await service.get_ticket_stats_by_category()
    recent_tickets = await service.get_tickets(
        pagination=PaginationParams(page=1, size=10),
        user_id=None,
        assigned_to=None,
        status=None,
        priority=None,
        category=None,
        search=None,
    )
    open_tickets = await service.get_open_tickets()
    
    return TicketDashboard(
        stats=TicketStats(**stats),
        stats_by_priority=TicketStatsByPriority(**stats_by_priority),
        stats_by_category=TicketStatsByCategory(**stats_by_category),
        recent_tickets=recent_tickets["tickets"][:5],
        open_tickets=open_tickets[:5],
    )