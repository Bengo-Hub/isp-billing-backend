"""Licence management API endpoints."""

from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.licence import LicenceStatus, LicenceType, LicencePaymentStatus
from app.schemas.licence import (
    Licence,
    LicenceCreate,
    LicenceUpdate,
    LicenceList,
    LicencePayment,
    LicencePaymentCreate,
    LicencePaymentUpdate,
    LicencePaymentList,
    LicenceUsageLog,
    LicenceUsageLogCreate,
    LicenceAnalytics,
    LicenceEarningsResponse,
    LicenceRenewalRequest,
    LicenceRenewalResponse,
    LicenceDashboard,
    LicenceStatusCheck
)
from app.services.licence_service import LicenceService
from app.core.exceptions import ValidationError

router = APIRouter()


@router.get("/", response_model=LicenceList)
async def get_licences(
    pagination: PaginationParams = Depends(),
    status: Optional[LicenceStatus] = Query(None, description="Filter by licence status"),
    licence_type: Optional[LicenceType] = Query(None, description="Filter by licence type"),
    search: Optional[str] = Query(None, description="Search in name, key, or organization"),
    expiring_soon: Optional[bool] = Query(None, description="Filter licences expiring within 30 days"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> LicenceList:
    """Get all licences with filtering and pagination."""
    service = LicenceService(db)
    
    try:
        result = await service.get_all_licences(
            pagination=pagination,
            status=status,
            licence_type=licence_type,
            search=search,
            expiring_soon=expiring_soon
        )
        return LicenceList(**result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/", response_model=Licence, status_code=status.HTTP_201_CREATED)
async def create_licence(
    licence_data: LicenceCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Licence:
    """Create a new licence."""
    service = LicenceService(db)
    
    try:
        licence = await service.create_licence(
            licence_data.dict(),
            created_by=current_user.id
        )
        return licence
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{licence_id}", response_model=Licence)
async def get_licence(
    licence_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Licence:
    """Get a specific licence by ID."""
    service = LicenceService(db)
    
    licence = await service.get_licence_by_id(licence_id)
    if not licence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Licence {licence_id} not found"
        )
    
    return licence


@router.patch("/{licence_id}", response_model=Licence)
async def update_licence(
    licence_id: int,
    licence_data: LicenceUpdate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Licence:
    """Update a licence."""
    service = LicenceService(db)
    
    try:
        licence = await service.update_licence(licence_id, licence_data.dict(exclude_unset=True))
        if not licence:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Licence {licence_id} not found"
            )
        return licence
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/{licence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_licence(
    licence_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a licence (admin only)."""
    service = LicenceService(db)
    
    licence = await service.get_licence_by_id(licence_id)
    if not licence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Licence {licence_id} not found"
        )
    
    try:
        await db.delete(licence)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/key/{licence_key}/status", response_model=LicenceStatusCheck)
async def check_licence_status(
    licence_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LicenceStatusCheck:
    """Check licence status by licence key."""
    service = LicenceService(db)
    
    status_data = await service.check_licence_status(licence_key)
    return LicenceStatusCheck(**status_data)


@router.post("/{licence_id}/renew", response_model=LicenceRenewalResponse)
async def renew_licence(
    licence_id: int,
    renewal_request: LicenceRenewalRequest,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> LicenceRenewalResponse:
    """Renew a licence subscription."""
    service = LicenceService(db)
    
    try:
        renewal_data = await service.renew_licence(
            licence_id=licence_id,
            renewal_months=renewal_request.renewal_months,
            payment_method=renewal_request.payment_method,
            amount=renewal_request.renewal_months * 50,  # Base cost calculation
            auto_renewal=renewal_request.auto_renewal
        )
        
        return LicenceRenewalResponse(
            licence_id=licence_id,
            payment_reference=renewal_data["payment_reference"],
            renewal_amount=renewal_data["amount"],
            new_expiry_date=renewal_data["new_expiry_date"],
            payment_url=f"/api/v1/licence/payments/{renewal_data['payment_id']}/pay",
            instructions="Complete payment to activate licence renewal"
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{licence_id}/analytics", response_model=LicenceAnalytics)
async def get_licence_analytics(
    licence_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> LicenceAnalytics:
    """Get comprehensive licence analytics."""
    service = LicenceService(db)
    
    try:
        analytics = await service.get_licence_analytics(licence_id)
        return LicenceAnalytics(**analytics)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{licence_id}/earnings", response_model=LicenceEarningsResponse)
async def get_licence_earnings(
    licence_id: int,
    period_type: str = Query("monthly", regex="^(daily|weekly|monthly)$"),
    months: int = Query(6, ge=1, le=24),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> LicenceEarningsResponse:
    """Get licence earnings data."""
    service = LicenceService(db)
    
    try:
        earnings = await service.get_licence_earnings(licence_id, period_type, months)
        return LicenceEarningsResponse(**earnings)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{licence_id}/dashboard", response_model=LicenceDashboard)
async def get_licence_dashboard(
    licence_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> LicenceDashboard:
    """Get licence dashboard data."""
    service = LicenceService(db)
    
    try:
        dashboard_data = await service.get_dashboard_data(licence_id)
        return LicenceDashboard(**dashboard_data)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Payment endpoints
@router.get("/{licence_id}/payments", response_model=LicencePaymentList)
async def get_licence_payments(
    licence_id: int,
    pagination: PaginationParams = Depends(),
    status: Optional[LicencePaymentStatus] = Query(None, description="Filter by payment status"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> LicencePaymentList:
    """Get licence payment history."""
    service = LicenceService(db)
    
    try:
        result = await service.get_licence_payments(
            licence_id=licence_id,
            pagination=pagination,
            status=status
        )
        return LicencePaymentList(**result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{licence_id}/payments", response_model=LicencePayment, status_code=status.HTTP_201_CREATED)
async def create_licence_payment(
    licence_id: int,
    payment_data: LicencePaymentCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> LicencePayment:
    """Record a licence payment."""
    service = LicenceService(db)
    
    try:
        payment_data.licence_id = licence_id
        payment = await service.create_licence_payment(payment_data.dict())
        return payment
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/payments/{payment_reference}/process")
async def process_licence_payment(
    payment_reference: str,
    external_transaction_id: str = Query(..., description="External payment transaction ID"),
    gateway_response: Optional[str] = Query(None, description="Payment gateway response"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Process a licence payment and update licence status."""
    service = LicenceService(db)
    
    success = await service.process_licence_payment(
        payment_reference=payment_reference,
        external_transaction_id=external_transaction_id,
        gateway_response=gateway_response
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process payment {payment_reference}"
        )
    
    return {
        "message": "Payment processed successfully",
        "payment_reference": payment_reference,
        "transaction_id": external_transaction_id
    }


# Usage tracking endpoints
@router.post("/{licence_id}/usage", response_model=LicenceUsageLog, status_code=status.HTTP_201_CREATED)
async def record_licence_usage(
    licence_id: int,
    usage_data: LicenceUsageLogCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LicenceUsageLog:
    """Record licence usage data."""
    service = LicenceService(db)
    
    try:
        usage_data.licence_id = licence_id
        success = await service.update_licence_usage(
            licence_id=licence_id,
            usage_data=usage_data.dict(),
            log_type=usage_data.log_type
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to record usage data"
            )
        
        # Return the created/updated usage log
        # This is a simplified response - in production you'd return the actual log
        return LicenceUsageLog(**usage_data.dict(), id=0, created_at=datetime.utcnow())
        
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Alert endpoints
@router.get("/{licence_id}/alerts")
async def get_licence_alerts(
    licence_id: int,
    active_only: bool = Query(True, description="Show only active alerts"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get licence alerts."""
    service = LicenceService(db)
    
    try:
        alerts = await service.get_licence_alerts(licence_id, active_only=active_only)
        return [
            {
                "id": alert.id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "title": alert.title,
                "message": alert.message,
                "action_required": alert.action_required,
                "is_acknowledged": alert.is_acknowledged,
                "created_at": alert.created_at.isoformat()
            }
            for alert in alerts
        ]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_licence_alert(
    alert_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Acknowledge a licence alert."""
    service = LicenceService(db)
    
    success = await service.acknowledge_alert(alert_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found"
        )
    
    return {"message": "Alert acknowledged successfully", "alert_id": alert_id}


# Utility endpoints
@router.get("/types", response_model=List[Dict[str, str]])
async def get_licence_types(
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, str]]:
    """Get available licence types."""
    return [
        {"value": LicenceType.TRIAL.value, "label": "Trial Licence (30 days)"},
        {"value": LicenceType.BASIC.value, "label": "Basic Licence"},
        {"value": LicenceType.PROFESSIONAL.value, "label": "Professional Licence"},
        {"value": LicenceType.ENTERPRISE.value, "label": "Enterprise Licence"},
        {"value": LicenceType.CUSTOM.value, "label": "Custom Licence"},
    ]


@router.get("/features", response_model=Dict[str, Dict[str, Any]])
async def get_licence_features(
    licence_type: Optional[LicenceType] = Query(None, description="Get features for specific licence type"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Dict[str, Any]]:
    """Get available licence features."""
    service = LicenceService(db)
    
    if licence_type:
        features = await service._get_default_features(licence_type)
        return {licence_type.value: features}
    else:
        # Return all licence type features
        all_features = {}
        for lt in LicenceType:
            all_features[lt.value] = await service._get_default_features(lt)
        return all_features


@router.post("/monitor-expiry")
async def monitor_licence_expiry(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Monitor all licences for expiry (admin task)."""
    service = LicenceService(db)
    
    try:
        result = await service.monitor_licence_expiry()
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/stats/summary")
async def get_licence_stats_summary(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get licence statistics summary."""
    service = LicenceService(db)
    
    try:
        # Get licence counts by status
        result = await db.execute(
            select(
                Licence.status,
                func.count(Licence.id).label('count')
            ).group_by(Licence.status)
        )
        status_counts = {row.status.value: row.count for row in result}

        # Get licence counts by type
        result = await db.execute(
            select(
                Licence.licence_type,
                func.count(Licence.id).label('count')
            ).group_by(Licence.licence_type)
        )
        type_counts = {row.licence_type.value: row.count for row in result}

        # Get expiring licences count
        expiry_threshold = datetime.utcnow() + timedelta(days=30)
        result = await db.execute(
            select(func.count(Licence.id))
            .where(
                and_(
                    Licence.expiry_date <= expiry_threshold,
                    Licence.status == LicenceStatus.ACTIVE
                )
            )
        )
        expiring_count = result.scalar() or 0

        # Get total revenue
        result = await db.execute(
            select(func.sum(LicencePayment.amount))
            .where(LicencePayment.status == LicencePaymentStatus.COMPLETED)
        )
        total_revenue = result.scalar() or 0

        return {
            "total_licences": sum(status_counts.values()),
            "status_breakdown": status_counts,
            "type_breakdown": type_counts,
            "expiring_soon": expiring_count,
            "total_revenue": float(total_revenue),
            "last_updated": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
