"""Provisioning API endpoints for MikroTik device setup and configuration."""

from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_technician_or_admin, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.provisioning import ProvisioningStatus, ProvisioningStep, ServiceType, ProvisioningPriority
from app.schemas.provisioning import (
    ProvisioningSession,
    ProvisioningSessionCreate,
    ProvisioningSessionUpdate,
    ProvisioningSessionList,
    ProvisioningWorkflowRequest,
    ProvisioningWorkflowResponse,
    ProvisioningStatusResponse,
    ProvisioningCancelRequest,
    ProvisioningRetryRequest,
    ProvisioningTemplate,
    ProvisioningTemplateCreate,
    ProvisioningTemplateUpdate,
    ProvisioningTemplateList,
    ProvisioningStepLog,
    ProvisioningCommand,
    RouterConfiguration,
    RouterConfigurationCreate
)
from app.services.provisioning_service import ProvisioningService
from app.core.exceptions import ProvisioningError, ValidationError

router = APIRouter()


@router.post("/workflow", response_model=ProvisioningWorkflowResponse)
async def start_provisioning_workflow(
    workflow_request: ProvisioningWorkflowRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningWorkflowResponse:
    """Start a complete provisioning workflow for a router.
    
    This is the main endpoint that initiates the 3-step provisioning process:
    1. Connection & Verification
    2. Basic Configuration
    3. Service Setup (PPPoE/Hotspot)
    """
    service = ProvisioningService(db)
    
    try:
        # Create provisioning session
        session = await service.create_provisioning_session(
            router_id=workflow_request.router_id,
            user_id=current_user.id,
            service_type=workflow_request.service_type,
            configuration=workflow_request.configuration,
            priority=workflow_request.priority,
            template_id=workflow_request.template_id,
            scheduled_at=workflow_request.scheduled_at
        )

        # Start provisioning if auto_start is enabled
        if workflow_request.auto_start:
            success = await service.start_provisioning(session.session_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to start provisioning process"
                )

        # Estimate duration based on service type
        estimated_duration = 15  # Base time
        if workflow_request.service_type == ServiceType.BOTH:
            estimated_duration = 25
        elif workflow_request.service_type == ServiceType.HOTSPOT:
            estimated_duration = 20

        return ProvisioningWorkflowResponse(
            session_id=session.session_id,
            status=session.status,
            message="Provisioning workflow started successfully",
            estimated_duration_minutes=estimated_duration,
            steps=[
                {"step": "connection", "description": "Device connection and verification"},
                {"step": "configuration", "description": "Basic router configuration"},
                {"step": "service_setup", "description": f"{workflow_request.service_type.value} service setup"}
            ]
        )

    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ProvisioningError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/sessions", response_model=ProvisioningSessionList)
async def get_provisioning_sessions(
    pagination: PaginationParams = Depends(),
    router_id: Optional[int] = Query(None, description="Filter by router ID"),
    status: Optional[ProvisioningStatus] = Query(None, description="Filter by status"),
    service_type: Optional[ServiceType] = Query(None, description="Filter by service type"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    priority: Optional[ProvisioningPriority] = Query(None, description="Filter by priority"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningSessionList:
    """Get provisioning sessions with filtering and pagination."""
    service = ProvisioningService(db)
    
    try:
        result = await service.get_sessions(
            pagination=pagination,
            router_id=router_id,
            status=status,
            service_type=service_type,
            user_id=user_id,
            priority=priority
        )
        return ProvisioningSessionList(**result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/sessions", response_model=ProvisioningSession, status_code=status.HTTP_201_CREATED)
async def create_provisioning_session(
    session_data: ProvisioningSessionCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningSession:
    """Create a new provisioning session without starting it."""
    service = ProvisioningService(db)
    
    try:
        session = await service.create_provisioning_session(
            router_id=session_data.router_id,
            user_id=current_user.id,
            service_type=session_data.service_type,
            configuration=session_data.configuration or {},
            priority=session_data.priority,
            scheduled_at=session_data.scheduled_at
        )
        return session
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ProvisioningError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/sessions/{session_id}", response_model=ProvisioningSession)
async def get_provisioning_session(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningSession:
    """Get a specific provisioning session by ID."""
    service = ProvisioningService(db)
    
    session = await service.get_session_by_id(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning session {session_id} not found"
        )
    
    return session


@router.patch("/sessions/{session_id}", response_model=ProvisioningSession)
async def update_provisioning_session(
    session_id: str,
    session_data: ProvisioningSessionUpdate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningSession:
    """Update a provisioning session."""
    service = ProvisioningService(db)
    
    try:
        session = await service.update_session(session_id, session_data.dict(exclude_unset=True))
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provisioning session {session_id} not found"
            )
        return session
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provisioning_session(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a provisioning session (only if not active)."""
    service = ProvisioningService(db)
    
    success = await service.delete_session(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning session {session_id} not found or cannot be deleted"
        )


@router.post("/sessions/{session_id}/start")
async def start_provisioning_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Start a provisioning session."""
    service = ProvisioningService(db)
    
    success = await service.start_provisioning(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to start provisioning session {session_id}"
        )
    
    return {"message": "Provisioning started successfully", "session_id": session_id}


@router.get("/sessions/{session_id}/status", response_model=ProvisioningStatusResponse)
async def get_provisioning_status(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningStatusResponse:
    """Get real-time status of a provisioning session."""
    service = ProvisioningService(db)
    
    status_data = await service.get_session_status(session_id)
    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning session {session_id} not found"
        )
    
    return ProvisioningStatusResponse(**status_data)


@router.post("/sessions/{session_id}/cancel")
async def cancel_provisioning_session(
    session_id: str,
    cancel_request: ProvisioningCancelRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Cancel an active provisioning session."""
    service = ProvisioningService(db)
    
    success = await service.cancel_provisioning(
        session_id=session_id,
        reason=cancel_request.reason,
        force=cancel_request.force_cancel
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to cancel provisioning session {session_id}"
        )
    
    return {"message": "Provisioning cancelled successfully", "session_id": session_id}


@router.post("/sessions/{session_id}/retry")
async def retry_provisioning_session(
    session_id: str,
    retry_request: ProvisioningRetryRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Retry a failed provisioning session."""
    service = ProvisioningService(db)
    
    try:
        success = await service.retry_provisioning(
            session_id=session_id,
            from_step=retry_request.from_step,
            reset_configuration=retry_request.reset_configuration,
            updated_configuration=retry_request.updated_configuration
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to retry provisioning session {session_id}"
            )
        
        return {"message": "Provisioning retry started successfully", "session_id": session_id}
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/sessions/{session_id}/steps", response_model=List[ProvisioningStepLog])
async def get_provisioning_steps(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[ProvisioningStepLog]:
    """Get detailed step logs for a provisioning session."""
    service = ProvisioningService(db)
    
    steps = await service.get_session_steps(session_id)
    if steps is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning session {session_id} not found"
        )
    
    return steps


@router.get("/sessions/{session_id}/commands", response_model=List[ProvisioningCommand])
async def get_provisioning_commands(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[ProvisioningCommand]:
    """Get executed commands for a provisioning session."""
    service = ProvisioningService(db)
    
    commands = await service.get_session_commands(session_id)
    if commands is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning session {session_id} not found"
        )
    
    return commands


# Template management endpoints
@router.get("/templates", response_model=ProvisioningTemplateList)
async def get_provisioning_templates(
    pagination: PaginationParams = Depends(),
    service_type: Optional[ServiceType] = Query(None, description="Filter by service type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search in name and description"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningTemplateList:
    """Get provisioning templates with filtering and pagination."""
    service = ProvisioningService(db)
    
    try:
        result = await service.get_templates(
            pagination=pagination,
            service_type=service_type,
            is_active=is_active,
            search=search
        )
        return ProvisioningTemplateList(**result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/templates", response_model=ProvisioningTemplate, status_code=status.HTTP_201_CREATED)
async def create_provisioning_template(
    template_data: ProvisioningTemplateCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningTemplate:
    """Create a new provisioning template."""
    service = ProvisioningService(db)
    
    try:
        template = await service.create_template(template_data, current_user.id)
        return template
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/templates/{template_id}", response_model=ProvisioningTemplate)
async def get_provisioning_template(
    template_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningTemplate:
    """Get a specific provisioning template."""
    service = ProvisioningService(db)
    
    template = await service.get_template_by_id(template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning template {template_id} not found"
        )
    
    return template


@router.patch("/templates/{template_id}", response_model=ProvisioningTemplate)
async def update_provisioning_template(
    template_id: int,
    template_data: ProvisioningTemplateUpdate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningTemplate:
    """Update a provisioning template."""
    service = ProvisioningService(db)
    
    try:
        template = await service.update_template(template_id, template_data.dict(exclude_unset=True))
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provisioning template {template_id} not found"
            )
        return template
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provisioning_template(
    template_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a provisioning template."""
    service = ProvisioningService(db)
    
    success = await service.delete_template(template_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning template {template_id} not found"
        )


@router.post("/templates/{template_id}/duplicate", response_model=ProvisioningTemplate)
async def duplicate_provisioning_template(
    template_id: int,
    new_name: str = Query(..., description="Name for the duplicated template"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ProvisioningTemplate:
    """Duplicate an existing provisioning template."""
    service = ProvisioningService(db)
    
    try:
        template = await service.duplicate_template(template_id, new_name, current_user.id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provisioning template {template_id} not found"
            )
        return template
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Router configuration endpoints
@router.get("/routers/{router_id}/configurations", response_model=List[RouterConfiguration])
async def get_router_configurations(
    router_id: int,
    configuration_type: Optional[str] = Query(None, description="Filter by configuration type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[RouterConfiguration]:
    """Get configuration history for a router."""
    service = ProvisioningService(db)
    
    configurations = await service.get_router_configurations(
        router_id=router_id,
        configuration_type=configuration_type,
        is_active=is_active
    )
    
    return configurations


@router.post("/routers/{router_id}/configurations", response_model=RouterConfiguration)
async def create_router_configuration(
    router_id: int,
    config_data: RouterConfigurationCreate,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> RouterConfiguration:
    """Create a router configuration backup."""
    service = ProvisioningService(db)
    
    try:
        config_data.router_id = router_id
        configuration = await service.create_router_configuration(config_data, current_user.id)
        return configuration
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/routers/{router_id}/configurations/{config_id}/restore")
async def restore_router_configuration(
    router_id: int,
    config_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Restore a router to a previous configuration."""
    service = ProvisioningService(db)
    
    try:
        success = await service.restore_router_configuration(
            router_id=router_id,
            config_id=config_id,
            user_id=current_user.id
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to restore router configuration"
            )
        
        return {
            "message": "Configuration restore started successfully",
            "router_id": router_id,
            "config_id": config_id
        }
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Utility endpoints
@router.get("/service-types", response_model=List[Dict[str, str]])
async def get_service_types(
    current_user: User = Depends(require_technician_or_admin()),
) -> List[Dict[str, str]]:
    """Get available service types for provisioning."""
    return [
        {"value": ServiceType.HOTSPOT.value, "label": "Hotspot Service"},
        {"value": ServiceType.PPPOE_SERVER.value, "label": "PPPoE Server"},
        {"value": ServiceType.BOTH.value, "label": "Both Services"},
        {"value": ServiceType.BRIDGE.value, "label": "Bridge Mode"},
    ]


@router.get("/priorities", response_model=List[Dict[str, str]])
async def get_provisioning_priorities(
    current_user: User = Depends(require_technician_or_admin()),
) -> List[Dict[str, str]]:
    """Get available provisioning priorities."""
    return [
        {"value": ProvisioningPriority.LOW.value, "label": "Low Priority"},
        {"value": ProvisioningPriority.NORMAL.value, "label": "Normal Priority"},
        {"value": ProvisioningPriority.HIGH.value, "label": "High Priority"},
        {"value": ProvisioningPriority.URGENT.value, "label": "Urgent Priority"},
    ]


@router.get("/default-configuration/{service_type}")
async def get_default_configuration(
    service_type: ServiceType,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get default configuration for a service type."""
    service = ProvisioningService(db)
    
    default_config = await service.get_default_configuration(service_type)
    return {"service_type": service_type.value, "configuration": default_config}


@router.post("/validate-configuration")
async def validate_provisioning_configuration(
    service_type: ServiceType,
    configuration: Dict[str, Any],
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Validate a provisioning configuration."""
    service = ProvisioningService(db)
    
    try:
        validated_config = await service.validate_configuration(service_type, configuration)
        return {
            "valid": True,
            "configuration": validated_config,
            "warnings": []
        }
    except ValidationError as e:
        return {
            "valid": False,
            "errors": [str(e)],
            "configuration": configuration
        }


@router.get("/stats", response_model=Dict[str, Any])
async def get_provisioning_stats(
    days: int = Query(30, ge=1, le=365, description="Number of days to include in stats"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get provisioning statistics."""
    service = ProvisioningService(db)
    
    stats = await service.get_provisioning_stats(days=days)
    return stats
