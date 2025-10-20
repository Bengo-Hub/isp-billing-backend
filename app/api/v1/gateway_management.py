"""Gateway management API endpoints for testing and monitoring."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.user import User
from app.services.gateway_management_service import GatewayManagementService
from app.core.exceptions import ValidationError, ExternalServiceError

router = APIRouter()


@router.get("/status", response_model=Dict[str, Any])
async def get_all_gateway_statuses(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get status of all configured gateways."""
    service = GatewayManagementService(db)
    return await service.get_all_gateway_statuses()


@router.get("/status/{gateway_type}/{provider}", response_model=Dict[str, Any])
async def get_gateway_status(
    gateway_type: str,
    provider: str,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get status of a specific gateway."""
    service = GatewayManagementService(db)
    
    try:
        return await service.get_gateway_status(gateway_type, provider)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/test/{gateway_type}/{provider}", response_model=Dict[str, Any])
async def test_gateway(
    gateway_type: str,
    provider: str,
    test_config: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Test a specific gateway configuration."""
    service = GatewayManagementService(db)
    
    try:
        return await service.test_gateway(gateway_type, provider, test_config)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ExternalServiceError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/test-all", response_model=Dict[str, Any])
async def test_all_gateways(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Test all configured gateways."""
    service = GatewayManagementService(db)
    return await service.test_all_gateways()


@router.get("/configuration/{gateway_type}/{provider}", response_model=Dict[str, Any])
async def get_gateway_configuration(
    gateway_type: str,
    provider: str,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get gateway configuration (sensitive fields masked)."""
    service = GatewayManagementService(db)
    
    try:
        return await service.get_gateway_configuration(gateway_type, provider)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/configuration/{gateway_type}/{provider}", response_model=Dict[str, Any])
async def update_gateway_configuration(
    gateway_type: str,
    provider: str,
    configuration: Dict[str, Any],
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Update gateway configuration."""
    service = GatewayManagementService(db)
    
    try:
        return await service.update_gateway_configuration(gateway_type, provider, configuration)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/configuration/{gateway_type}/{provider}/validate", response_model=Dict[str, Any])
async def validate_gateway_configuration(
    gateway_type: str,
    provider: str,
    configuration: Dict[str, Any],
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Validate gateway configuration without saving."""
    service = GatewayManagementService(db)
    
    try:
        return await service.validate_gateway_configuration(gateway_type, provider, configuration)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/available", response_model=Dict[str, Any])
async def get_available_gateways(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get list of available gateways and their capabilities."""
    service = GatewayManagementService(db)
    return await service.get_available_gateways()


@router.get("/history/{gateway_type}/{provider}", response_model=List[Dict[str, Any]])
async def get_gateway_test_history(
    gateway_type: str,
    provider: str,
    days: int = Query(7, ge=1, le=90, description="Number of days to include"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get test history for a gateway."""
    service = GatewayManagementService(db)
    
    try:
        return await service.get_gateway_test_history(gateway_type, provider, days)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/statistics", response_model=Dict[str, Any])
async def get_gateway_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to include"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get gateway usage and performance statistics."""
    service = GatewayManagementService(db)
    return await service.get_gateway_statistics(days)


@router.post("/monitor", response_model=Dict[str, Any])
async def monitor_gateway_health(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Monitor health of all gateways and send alerts."""
    service = GatewayManagementService(db)
    return await service.monitor_gateway_health()


@router.post("/maintenance/cleanup-logs", response_model=Dict[str, int])
async def cleanup_old_test_logs(
    days: int = Query(30, ge=1, le=365, description="Delete logs older than this many days"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, int]:
    """Clean up old gateway test logs."""
    service = GatewayManagementService(db)
    
    cleanup_count = await service.cleanup_old_test_logs(days)
    return {"cleaned_up_logs": cleanup_count}
