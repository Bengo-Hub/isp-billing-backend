"""
Platform Owner API - Analytics.

Endpoints for platform-wide analytics and reporting.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import require_platform_owner
from app.models.user import User
from app.models.organization import Organization, OrganizationStatus
# Platform revenue/invoices are owned by treasury now; the platform-billing models
# (PlatformInvoice/PlatformPayment/tiers) were retired. Revenue metrics here read 0
# (the authoritative figures live in treasury / the books console link-out).

router = APIRouter(prefix="/analytics", tags=["Platform - Analytics"])


# =========================================================================
# Schemas
# =========================================================================

class DashboardStats(BaseModel):
    """Platform dashboard statistics."""

    # Organization metrics
    total_organizations: int
    active_organizations: int
    trial_organizations: int
    suspended_organizations: int

    # Revenue metrics
    total_revenue_this_month: float
    total_revenue_last_month: float
    revenue_growth_percentage: float

    # Customer metrics
    total_end_customers: int
    active_end_customers: int

    # Subscription metrics
    new_signups_this_month: int
    churn_this_month: int
    churn_rate: float

    # Payment metrics
    pending_payments: float
    overdue_payments: float
    collection_rate: float


class RevenueChartData(BaseModel):
    """Revenue chart data point."""

    date: str
    revenue: float
    invoiced: float
    collected: float


class OrganizationGrowthData(BaseModel):
    """Organization growth data point."""

    date: str
    new_signups: int
    churned: int
    total_active: int


class TopOrganization(BaseModel):
    """Top performing organization."""

    id: int
    name: str
    slug: str
    revenue: float
    customers: int
    organization_type: str


class AnalyticsResponse(BaseModel):
    """Full analytics response."""

    dashboard: DashboardStats
    revenue_chart: List[RevenueChartData]
    organization_growth: List[OrganizationGrowthData]
    top_organizations: List[TopOrganization]


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get platform dashboard statistics.

    Platform owner only.
    """
    now = datetime.utcnow()
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_of_last_month = (first_of_month - timedelta(days=1)).replace(day=1)

    # Organization counts by status (exclude platform org)
    org_result = await db.execute(
        select(Organization.status, func.count(Organization.id))
        .where(Organization.auth_tenant_id.isnot(None))
        .group_by(Organization.status)
    )
    org_counts = {row[0]: row[1] for row in org_result.all()}

    total_orgs = sum(org_counts.values())
    active_orgs = org_counts.get(OrganizationStatus.ACTIVE, 0)
    trial_orgs = org_counts.get(OrganizationStatus.TRIAL, 0)
    suspended_orgs = org_counts.get(OrganizationStatus.SUSPENDED, 0)

    # Platform revenue is owned by treasury now — report 0 (books console link-out).
    revenue_this_month = 0.0
    revenue_last_month = 0.0
    growth = 0

    # Total end customers (from all organizations)
    total_customers = await db.execute(
        select(func.sum(Organization.total_customers))
    )
    total_end_customers = int(total_customers.scalar() or 0)

    active_subs = await db.execute(
        select(func.sum(Organization.active_subscriptions))
    )
    active_end_customers = int(active_subs.scalar() or 0)

    # New signups this month (exclude platform org)
    new_signups = await db.execute(
        select(func.count(Organization.id))
        .where(
            Organization.created_at >= first_of_month,
            Organization.auth_tenant_id.isnot(None)
        )
    )
    new_signups_count = new_signups.scalar() or 0

    # Churn this month (organizations that became suspended, exclude platform org)
    churned = await db.execute(
        select(func.count(Organization.id))
        .where(
            Organization.status == OrganizationStatus.SUSPENDED,
            Organization.suspended_at >= first_of_month,
            Organization.auth_tenant_id.isnot(None)
        )
    )
    churn_count = churned.scalar() or 0

    # Churn rate
    if active_orgs + trial_orgs > 0:
        churn_rate = (churn_count / (active_orgs + trial_orgs)) * 100
    else:
        churn_rate = 0

    # Platform invoices/collections owned by treasury now — report 0.
    pending = 0.0
    overdue = 0.0
    collection_rate = 100

    return DashboardStats(
        total_organizations=total_orgs,
        active_organizations=active_orgs,
        trial_organizations=trial_orgs,
        suspended_organizations=suspended_orgs,
        total_revenue_this_month=revenue_this_month,
        total_revenue_last_month=revenue_last_month,
        revenue_growth_percentage=growth,
        total_end_customers=total_end_customers,
        active_end_customers=active_end_customers,
        new_signups_this_month=new_signups_count,
        churn_this_month=churn_count,
        churn_rate=churn_rate,
        pending_payments=pending,
        overdue_payments=overdue,
        collection_rate=collection_rate,
    )


@router.get("/revenue-chart", response_model=List[RevenueChartData])
async def get_revenue_chart(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
    days: int = Query(30, ge=7, le=365),
):
    """
    Get revenue chart data.

    Platform owner only.
    """
    now = datetime.utcnow()
    start_date = now - timedelta(days=days)

    # Platform revenue/invoices owned by treasury now — empty series here.
    revenue_by_date: dict = {}
    invoiced_by_date: dict = {}

    # Generate chart data for each day
    chart_data = []
    current = start_date.date()
    end = now.date()

    while current <= end:
        chart_data.append(RevenueChartData(
            date=current.isoformat(),
            revenue=revenue_by_date.get(current, 0),
            invoiced=invoiced_by_date.get(current, 0),
            collected=revenue_by_date.get(current, 0),
        ))
        current += timedelta(days=1)

    return chart_data


@router.get("/organization-growth", response_model=List[OrganizationGrowthData])
async def get_organization_growth(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
    months: int = Query(12, ge=1, le=24),
):
    """
    Get organization growth chart data.

    Platform owner only.
    """
    now = datetime.utcnow()
    start_date = now - timedelta(days=months * 30)

    # Get monthly signups (database-agnostic approach, exclude platform org)
    signups_result = await db.execute(
        select(Organization.created_at)
        .where(
            Organization.created_at >= start_date,
            Organization.auth_tenant_id.isnot(None)
        )
    )
    signups_by_month = {}
    for row in signups_result.all():
        month_key = row[0].replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        signups_by_month[month_key] = signups_by_month.get(month_key, 0) + 1

    # Get monthly churn (database-agnostic approach, exclude platform org)
    churn_result = await db.execute(
        select(Organization.suspended_at)
        .where(
            Organization.suspended_at >= start_date,
            Organization.suspended_at.isnot(None),
            Organization.auth_tenant_id.isnot(None)
        )
    )
    churn_by_month = {}
    for row in churn_result.all():
        if row[0]:
            month_key = row[0].replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            churn_by_month[month_key] = churn_by_month.get(month_key, 0) + 1

    # Generate chart data
    chart_data = []
    total_active = 0

    current = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    while current <= end:
        new = signups_by_month.get(current, 0)
        churned = churn_by_month.get(current, 0)
        total_active += new - churned

        chart_data.append(OrganizationGrowthData(
            date=current.strftime("%Y-%m"),
            new_signups=new,
            churned=churned,
            total_active=max(0, total_active),
        ))

        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return chart_data


@router.get("/top-organizations", response_model=List[TopOrganization])
async def get_top_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Get top performing organizations by revenue.

    Platform owner only.
    """
    result = await db.execute(
        select(Organization)
        .where(
            Organization.status.in_([OrganizationStatus.ACTIVE, OrganizationStatus.TRIAL]),
            Organization.auth_tenant_id.isnot(None)  # Exclude platform org
        )
        .order_by(Organization.total_revenue.desc())
        .limit(limit)
    )
    organizations = list(result.scalars().all())

    return [
        TopOrganization(
            id=org.id,
            name=org.name,
            slug=org.slug,
            revenue=float(org.total_revenue) / 100,  # Convert from cents
            customers=org.total_customers,
            organization_type=org.organization_type.value,
        )
        for org in organizations
    ]


@router.get("/", response_model=AnalyticsResponse)
async def get_full_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get full analytics data including dashboard, charts, and top organizations.

    Platform owner only.
    """
    # Get all analytics in one call
    dashboard = await get_dashboard_stats(db, current_user)
    revenue_chart = await get_revenue_chart(db, current_user, days=30)
    org_growth = await get_organization_growth(db, current_user, months=12)
    top_orgs = await get_top_organizations(db, current_user, limit=10)

    return AnalyticsResponse(
        dashboard=dashboard,
        revenue_chart=revenue_chart,
        organization_growth=org_growth,
        top_organizations=top_orgs,
    )
