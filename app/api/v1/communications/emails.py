"""Emails API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.email import EmailStatus
from app.schemas.email import (
    Email, EmailCreate, EmailListResponse
)
from app.modules.emails import EmailService

router = APIRouter()


@router.get("/", response_model=EmailListResponse)
async def get_emails(
    pagination: PaginationParams = Depends(),
    status_filter: Optional[EmailStatus] = Query(None, alias="status"),
    campaign_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailListResponse:
    """Get all emails with pagination and filters."""
    service = EmailService(db, current_user.organization_id, current_user.id)
    result = await service.get_all(
        pagination=pagination,
        status=status_filter,
        campaign_id=campaign_id,
        search=search,
    )
    return EmailListResponse(**result)


@router.post("/send", response_model=Email, status_code=status.HTTP_201_CREATED)
async def send_email(
    email_data: EmailCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Email:
    """Send an email (creates email record for processing)."""
    service = EmailService(db, current_user.organization_id, current_user.id)
    try:
        email = await service.send_email(
            to_email=email_data.to_email,
            subject=email_data.subject,
            body_html=email_data.body_html,
            body_text=email_data.body_text,
            to_name=email_data.to_name,
            cc=email_data.cc,
            bcc=email_data.bcc,
            attachments=email_data.attachments,
            template_name=email_data.template_name,
            template_data=email_data.template_data,
            campaign_id=email_data.campaign_id,
        )
        return email
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{email_id}", response_model=Email)
async def get_email(
    email_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Email:
    """Get email by ID."""
    service = EmailService(db, current_user.organization_id, current_user.id)
    email = await service.get_by_id(email_id)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not found"
        )
    return email
