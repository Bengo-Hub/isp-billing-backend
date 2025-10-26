"""
Workflow endpoints for MikroTik provisioning.
Handles the main provisioning workflow and session management.
"""
import logging
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from app.models.user import User
from app.api.deps import require_technician_or_admin
from app.services.provisioning_service import ProvisioningService

logger = logging.getLogger(__name__)
router = APIRouter()


class ProvisioningRequest(BaseModel):
    router_id: int
    configuration: Dict[str, Any]


class ProvisioningResponse(BaseModel):
    session_id: str
    status: str
    message: str


@router.post("/workflow", response_model=ProvisioningResponse)
async def start_provisioning_workflow(
    request: ProvisioningRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_technician_or_admin()),
):
    """Start the provisioning workflow for a MikroTik device."""
    try:
        provisioning_service = ProvisioningService()
        
        # Create a new provisioning session
        session = await provisioning_service.create_provisioning_session(
            router_id=request.router_id,
            configuration=request.configuration,
            user_id=current_user.id
        )
        
        # Start the provisioning process in the background
        background_tasks.add_task(
            provisioning_service.execute_provisioning_workflow,
            session.session_id
        )
        
        return ProvisioningResponse(
            session_id=session.session_id,
            status="started",
            message="Provisioning workflow started successfully"
        )
    
    except Exception as e:
        logger.error(f"Failed to start provisioning workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start provisioning: {e}")


@router.get("/sessions/{session_id}/status")
async def get_provisioning_status(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
):
    """Get the current status of a provisioning session."""
    try:
        provisioning_service = ProvisioningService()
        status = await provisioning_service.get_session_status(session_id)
        
        if not status:
            raise HTTPException(status_code=404, detail="Provisioning session not found")
        
        return status
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get provisioning status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get provisioning status")


@router.post("/sessions/{session_id}/cancel")
async def cancel_provisioning(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
):
    """Cancel a running provisioning session."""
    try:
        provisioning_service = ProvisioningService()
        success = await provisioning_service.cancel_session(session_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Provisioning session not found")
        
        return {"message": "Provisioning session cancelled successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel provisioning: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel provisioning")


@router.get("/sessions/{session_id}/logs")
async def get_provisioning_logs(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
):
    """Get the logs for a provisioning session."""
    try:
        provisioning_service = ProvisioningService()
        logs = await provisioning_service.get_session_logs(session_id)
        
        return {"logs": logs}
    
    except Exception as e:
        logger.error(f"Failed to get provisioning logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get provisioning logs")


@router.post("/sessions/{session_id}/retry")
async def retry_provisioning(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_technician_or_admin()),
):
    """Retry a failed provisioning session."""
    try:
        provisioning_service = ProvisioningService()
        
        # Reset the session status
        await provisioning_service.reset_session(session_id)
        
        # Start provisioning again
        background_tasks.add_task(
            provisioning_service.execute_provisioning_workflow,
            session_id
        )
        
        return {"message": "Provisioning retry started successfully"}
    
    except Exception as e:
        logger.error(f"Failed to retry provisioning: {e}")
        raise HTTPException(status_code=500, detail="Failed to retry provisioning")
