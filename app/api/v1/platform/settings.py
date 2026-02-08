"""Platform settings API endpoints (platform owner only)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import require_platform_owner
from app.models.platform_settings import PlatformSettings
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["Platform - Settings"])


class PlatformSettingsUpdate(BaseModel):
    """Schema for updating platform settings."""

    company_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    website_url: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    invoice_prefix: Optional[str] = None
    tax_rate: Optional[float] = None
    currency: Optional[str] = None
    terms_of_service: Optional[str] = None
    privacy_policy_url: Optional[str] = None
    default_trial_days: Optional[int] = None
    default_grace_period_days: Optional[int] = None


@router.get("/")
async def get_platform_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """Get platform settings. Platform owner only."""
    result = await db.execute(select(PlatformSettings).limit(1))
    settings = result.scalar_one_or_none()

    if not settings:
        return {
            "id": None,
            "company_name": "CodeVertex IT Solutions",
            "address": None,
            "city": None,
            "country": "Kenya",
            "phone": None,
            "mobile": None,
            "email": None,
            "website_url": None,
            "logo_url": "/images/logo/logo.png",
            "favicon_url": None,
            "primary_color": "#ec4899",
            "secondary_color": "#8b5cf6",
            "invoice_prefix": "INV",
            "tax_rate": 0,
            "currency": "KES",
            "default_trial_days": 14,
            "default_grace_period_days": 2,
        }

    return settings.to_dict()


@router.patch("/")
async def update_platform_settings(
    data: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """Update platform settings. Platform owner only."""
    result = await db.execute(select(PlatformSettings).limit(1))
    settings = result.scalar_one_or_none()

    if not settings:
        # Create settings if they don't exist
        settings = PlatformSettings()
        db.add(settings)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    await db.commit()
    await db.refresh(settings)

    return settings.to_dict()
