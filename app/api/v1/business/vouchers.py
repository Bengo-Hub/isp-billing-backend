"""Voucher management API endpoints for admin dashboard."""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.customer_portal import VoucherCode, VoucherStatus
from app.models.plan import ServicePlan
from app.models.organization import Organization
from app.api.deps import get_current_user, require_technician_or_admin
from app.api.deps_org import get_org_id_for_query

logger = logging.getLogger(__name__)

router = APIRouter()


# --------------- Schemas ---------------

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class VoucherStatusFilter(str, Enum):
    active = "active"
    used = "used"
    expired = "expired"
    disabled = "disabled"


class VoucherListItem(BaseModel):
    id: int
    code: str
    status: str
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    organization_id: Optional[int] = None
    hotspot_username: Optional[str] = None
    data_limit_bytes: Optional[int] = None
    time_limit_seconds: Optional[int] = None
    bandwidth_limit: Optional[str] = None
    used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    batch_id: Optional[int] = None

    class Config:
        from_attributes = True


class VoucherListResponse(BaseModel):
    vouchers: List[VoucherListItem]
    total: int
    page: int
    size: int
    pages: int


class VoucherStatsResponse(BaseModel):
    total_vouchers: int = 0
    active_vouchers: int = 0
    used_vouchers: int = 0
    expired_vouchers: int = 0


class VoucherCreateRequest(BaseModel):
    plan_id: int
    count: int = Field(default=1, ge=1, le=500)
    code_format: str = Field(default="XXXX-XXXX-XXXX")


class VoucherUpdateRequest(BaseModel):
    status: Optional[VoucherStatusFilter] = None
    expires_at: Optional[datetime] = None


# --------------- Endpoints ---------------


@router.get("/", response_model=VoucherListResponse)
async def list_vouchers(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Optional[VoucherStatusFilter] = None,
    search: Optional[str] = None,
    plan_id: Optional[int] = None,
    org_id: int = Depends(get_org_id_for_query),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all vouchers with pagination and filtering."""
    query = select(VoucherCode)
    count_query = select(func.count(VoucherCode.id))

    # Apply filters
    filters = [VoucherCode.organization_id == org_id]
    if status:
        filters.append(VoucherCode.status == status.value)
    if plan_id:
        filters.append(VoucherCode.plan_id == plan_id)
    if search:
        filters.append(
            or_(
                VoucherCode.code.ilike(f"%{search}%"),
                VoucherCode.hotspot_username.ilike(f"%{search}%"),
            )
        )

    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * size
    query = query.order_by(VoucherCode.created_at.desc()).offset(offset).limit(size)
    result = await db.execute(query)
    vouchers = result.scalars().all()

    # Fetch plan names
    plan_ids = {v.plan_id for v in vouchers if v.plan_id}
    plan_names = {}
    if plan_ids:
        plans_result = await db.execute(
            select(ServicePlan.id, ServicePlan.name).where(ServicePlan.id.in_(plan_ids))
        )
        plan_names = {row.id: row.name for row in plans_result}

    items = []
    for v in vouchers:
        items.append(VoucherListItem(
            id=v.id,
            code=v.code,
            status=v.status.value if hasattr(v.status, 'value') else str(v.status),
            plan_id=v.plan_id,
            plan_name=plan_names.get(v.plan_id),
            organization_id=v.organization_id,
            hotspot_username=v.hotspot_username,
            data_limit_bytes=v.data_limit_bytes,
            time_limit_seconds=v.time_limit_seconds,
            bandwidth_limit=v.bandwidth_limit,
            used_at=v.used_at,
            expires_at=v.expires_at,
            created_at=v.created_at,
            batch_id=v.batch_id,
        ))

    pages = (total + size - 1) // size if total > 0 else 0

    return VoucherListResponse(
        vouchers=items,
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


@router.get("/stats", response_model=VoucherStatsResponse)
async def get_voucher_stats(
    org_id: int = Depends(get_org_id_for_query),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get voucher statistics."""
    total_result = await db.execute(
        select(func.count(VoucherCode.id)).where(VoucherCode.organization_id == org_id)
    )
    total = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count(VoucherCode.id)).where(
            and_(VoucherCode.organization_id == org_id, VoucherCode.status == VoucherStatus.ACTIVE)
        )
    )
    active = active_result.scalar() or 0

    used_result = await db.execute(
        select(func.count(VoucherCode.id)).where(
            and_(VoucherCode.organization_id == org_id, VoucherCode.status == VoucherStatus.USED)
        )
    )
    used = used_result.scalar() or 0

    expired_result = await db.execute(
        select(func.count(VoucherCode.id)).where(
            and_(VoucherCode.organization_id == org_id, VoucherCode.status == VoucherStatus.EXPIRED)
        )
    )
    expired = expired_result.scalar() or 0

    return VoucherStatsResponse(
        total_vouchers=total,
        active_vouchers=active,
        used_vouchers=used,
        expired_vouchers=expired,
    )


@router.get("/{voucher_id}", response_model=VoucherListItem)
async def get_voucher(
    voucher_id: int,
    org_id: int = Depends(get_org_id_for_query),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get a single voucher by ID."""
    result = await db.execute(
        select(VoucherCode).where(
            and_(VoucherCode.id == voucher_id, VoucherCode.organization_id == org_id)
        )
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Get plan name
    plan_name = None
    if voucher.plan_id:
        plan_result = await db.execute(
            select(ServicePlan.name).where(ServicePlan.id == voucher.plan_id)
        )
        plan_name = plan_result.scalar_one_or_none()

    return VoucherListItem(
        id=voucher.id,
        code=voucher.code,
        status=voucher.status.value if hasattr(voucher.status, 'value') else str(voucher.status),
        plan_id=voucher.plan_id,
        plan_name=plan_name,
        organization_id=voucher.organization_id,
        hotspot_username=voucher.hotspot_username,
        data_limit_bytes=voucher.data_limit_bytes,
        time_limit_seconds=voucher.time_limit_seconds,
        bandwidth_limit=voucher.bandwidth_limit,
        used_at=voucher.used_at,
        expires_at=voucher.expires_at,
        created_at=voucher.created_at,
        batch_id=voucher.batch_id,
    )


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate_vouchers(
    data: VoucherCreateRequest,
    org_id: int = Depends(get_org_id_for_query),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_technician_or_admin),
):
    """Generate a batch of voucher codes for a plan."""
    # Verify plan exists
    plan_result = await db.execute(
        select(ServicePlan).where(ServicePlan.id == data.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    created = []
    for _ in range(data.count):
        code = VoucherCode.generate_code(format_pattern=data.code_format)
        voucher = VoucherCode(
            code=code,
            plan_id=plan.id,
            organization_id=org_id,
            status=VoucherStatus.ACTIVE,
            data_limit_bytes=plan.data_limit * 1024 * 1024 if plan.data_limit else None,
            time_limit_seconds=plan.time_limit * 60 if plan.time_limit else None,
            bandwidth_limit=f"{plan.download_speed}/{plan.upload_speed}" if plan.download_speed else None,
        )
        db.add(voucher)
        created.append(voucher)

    await db.commit()
    logger.info(f"Generated {len(created)} vouchers for plan {plan.name}")

    return {"message": f"Generated {len(created)} vouchers", "count": len(created)}


@router.patch("/{voucher_id}")
async def update_voucher(
    voucher_id: int,
    data: VoucherUpdateRequest,
    org_id: int = Depends(get_org_id_for_query),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_technician_or_admin),
):
    """Update a voucher (status/expiry)."""
    result = await db.execute(
        select(VoucherCode).where(
            and_(VoucherCode.id == voucher_id, VoucherCode.organization_id == org_id)
        )
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    if data.status:
        voucher.status = VoucherStatus(data.status.value)
    if data.expires_at is not None:
        voucher.expires_at = data.expires_at

    await db.commit()
    await db.refresh(voucher)
    return {"message": "Voucher updated successfully"}


@router.delete("/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voucher(
    voucher_id: int,
    org_id: int = Depends(get_org_id_for_query),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_technician_or_admin),
):
    """Delete a voucher."""
    result = await db.execute(
        select(VoucherCode).where(
            and_(VoucherCode.id == voucher_id, VoucherCode.organization_id == org_id)
        )
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    await db.delete(voucher)
    await db.commit()
