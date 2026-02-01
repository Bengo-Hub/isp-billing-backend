"""Email service."""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Email, EmailStatus
from app.api.deps import PaginationParams


class EmailService:
    """Email service."""

    def __init__(self, db: AsyncSession, organization_id: int, user_id: int):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id

    async def get_by_id(self, email_id: int) -> Optional[Email]:
        """Get email by ID."""
        query = select(Email).where(
            and_(
                Email.id == email_id,
                Email.organization_id == self.organization_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        pagination: PaginationParams,
        status: Optional[EmailStatus] = None,
        campaign_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all emails with pagination and filters."""
        query = select(Email).where(Email.organization_id == self.organization_id)

        # Apply filters
        if status:
            query = query.where(Email.status == status)
        if campaign_id:
            query = query.where(Email.campaign_id == campaign_id)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    Email.to_email.ilike(search_term),
                    Email.to_name.ilike(search_term),
                    Email.subject.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get emails with pagination
        query = query.order_by(Email.created_at.desc())
        query = query.offset(pagination.offset).limit(pagination.size)

        result = await self.db.execute(query)
        emails = result.scalars().all()

        return {
            "items": emails,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
        }

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: Optional[str] = None,
        body_text: Optional[str] = None,
        to_name: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[str] = None,
        template_name: Optional[str] = None,
        template_data: Optional[str] = None,
        campaign_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Email:
        """Create email record for sending."""
        email = Email(
            organization_id=self.organization_id,
            to_email=to_email,
            to_name=to_name,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            status=EmailStatus.PENDING,
            template_name=template_name,
            template_data=template_data,
            campaign_id=campaign_id,
            user_id=user_id,
            sent_by_user_id=self.user_id,
        )

        self.db.add(email)
        await self.db.commit()
        await self.db.refresh(email)

        # In production, this would trigger actual email sending via a queue
        # For now, we just create the record

        return email
