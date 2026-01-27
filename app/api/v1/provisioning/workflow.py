"""
Workflow endpoints for MikroTik provisioning.
Handles the main provisioning workflow and session management.
"""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.api.deps import require_technician_or_admin, get_db
from app.modules.provisioning import ProvisioningService

logger = logging.getLogger(__name__)
router = APIRouter()


class ProvisioningRequest(BaseModel):
    router_id: int
    configuration: Dict[str, Any]


class ProvisioningResponse(BaseModel):
    session_id: str
    status: str
    message: str


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    current_step: Optional[str] = None
    progress: Optional[int] = None
    steps: Optional[List[Dict[str, Any]]] = None
    error_message: Optional[str] = None


@router.post("/workflow", response_model=ProvisioningResponse)
async def start_provisioning_workflow(
    request: ProvisioningRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Start the provisioning workflow for a MikroTik device."""
    try:
        provisioning_service = ProvisioningService(db)

        # Create a new provisioning session
        session = await provisioning_service.create_provisioning_session(
            router_id=request.router_id,
            configuration=request.configuration,
            user_id=current_user.id
        )

        # Start the provisioning process in the background
        background_tasks.add_task(
            provisioning_service.start_provisioning,
            session.session_id
        )

        return ProvisioningResponse(
            session_id=session.session_id,
            status="started",
            message="Provisioning workflow started successfully"
        )

    except Exception as e:
        logger.error(f"Failed to start provisioning workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start provisioning: {str(e)}")


@router.get("/sessions/{session_id}/status", response_model=SessionStatusResponse)
async def get_provisioning_status(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Get the current status of a provisioning session."""
    try:
        provisioning_service = ProvisioningService(db)
        status = await provisioning_service.get_session_status(session_id)

        if not status:
            raise HTTPException(status_code=404, detail="Provisioning session not found")

        return SessionStatusResponse(**status)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get provisioning status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get provisioning status")


@router.post("/sessions/{session_id}/cancel")
async def cancel_provisioning(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Cancel a running provisioning session."""
    try:
        provisioning_service = ProvisioningService(db)
        success = await provisioning_service.cancel_provisioning(session_id)

        if not success:
            raise HTTPException(status_code=404, detail="Provisioning session not found or cannot be cancelled")

        return {"message": "Provisioning session cancelled successfully", "session_id": session_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel provisioning: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel provisioning")


@router.get("/sessions/{session_id}/logs")
async def get_provisioning_logs(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Get the logs for a provisioning session (steps and commands)."""
    try:
        provisioning_service = ProvisioningService(db)

        # Get both step logs and command logs
        steps = await provisioning_service.get_session_steps(session_id)
        commands = await provisioning_service.get_session_commands(session_id)

        if steps is None and commands is None:
            raise HTTPException(status_code=404, detail="Provisioning session not found")

        # Format the logs
        logs = []
        if steps:
            for step in steps:
                logs.append({
                    "type": "step",
                    "step": step.step.value if hasattr(step.step, 'value') else str(step.step),
                    "status": step.status.value if hasattr(step.status, 'value') else str(step.status),
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                    "error_message": step.error_message,
                })

        if commands:
            for cmd in commands:
                logs.append({
                    "type": "command",
                    "command": cmd.command,
                    "status": cmd.status.value if hasattr(cmd.status, 'value') else str(cmd.status),
                    "executed_at": cmd.executed_at.isoformat() if cmd.executed_at else None,
                    "result": cmd.result,
                    "error_message": cmd.error_message,
                })

        return {"session_id": session_id, "logs": logs}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get provisioning logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get provisioning logs")


@router.post("/sessions/{session_id}/retry")
async def retry_provisioning(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Retry a failed provisioning session."""
    try:
        provisioning_service = ProvisioningService(db)

        # Use the existing retry_provisioning method which handles reset internally
        success = await provisioning_service.retry_provisioning(session_id)

        if not success:
            raise HTTPException(status_code=400, detail="Cannot retry this provisioning session")

        return {
            "message": "Provisioning retry started successfully",
            "session_id": session_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry provisioning: {e}")
        raise HTTPException(status_code=500, detail="Failed to retry provisioning")


@router.get("/sessions")
async def list_provisioning_sessions(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    router_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """List all provisioning sessions with optional filters."""
    try:
        provisioning_service = ProvisioningService(db)
        sessions = await provisioning_service.get_sessions(
            skip=skip,
            limit=limit,
            status=status,
            router_id=router_id
        )

        return {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "router_id": s.router_id,
                    "status": s.status.value if hasattr(s.status, 'value') else str(s.status),
                    "service_type": s.service_type.value if hasattr(s.service_type, 'value') else str(s.service_type),
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                }
                for s in sessions
            ],
            "skip": skip,
            "limit": limit,
            "total": len(sessions)
        }

    except Exception as e:
        logger.error(f"Failed to list provisioning sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to list provisioning sessions")


@router.delete("/sessions/{session_id}")
async def delete_provisioning_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Delete a provisioning session (only if completed or failed)."""
    try:
        provisioning_service = ProvisioningService(db)
        success = await provisioning_service.delete_session(session_id)

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Session not found or cannot be deleted (still in progress)"
            )

        return {"message": "Provisioning session deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete provisioning session: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete provisioning session")


class DeviceStatusResponse(BaseModel):
    """Response model for device status check."""
    online: bool
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.get("/device-status/{router_id}", response_model=DeviceStatusResponse)
async def check_device_status(
    router_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """
    Check if a MikroTik device is online using stored API credentials.
    Used for reprovisioning auto-detection.
    """
    from app.models.router import Router
    from app.core.encryption import get_credential_encryption
    from sqlalchemy import select, update
    import librouteros
    
    try:
        # Fetch the router from database
        result = await db.execute(
            select(Router).where(Router.id == router_id)
        )
        router = result.scalar_one_or_none()
        
        if not router:
            raise HTTPException(status_code=404, detail="Router not found")
        
        # Check if router has stored API credentials
        if not router.api_credentials_encrypted:
            return DeviceStatusResponse(
                online=False,
                error="No stored API credentials found for this router"
            )
        
        # Decrypt the API credentials using the existing encryption service
        try:
            encryption = get_credential_encryption()
            creds_dict = encryption.decrypt_credentials(router.api_credentials_encrypted)
            username = creds_dict["username"]
            password = creds_dict["password"]
        except Exception as e:
            logger.error(f"Failed to decrypt API credentials: {e}")
            return DeviceStatusResponse(
                online=False,
                error="Failed to decrypt stored credentials"
            )
        
        # Try to connect to the device via API
        try:
            api = librouteros.connect(
                host=router.ip_address,
                username=username,
                password=password,
                port=router.port,
                timeout=3
            )
            
            # Test connection by getting system identity
            identity = api.path("/system/identity")
            identity_data = list(identity)
            
            # Get system resource info
            resource = api.path("/system/resource")
            resource_data = list(resource)
            
            api.close()
            
            # Update router status in database
            from datetime import datetime as dt
            await db.execute(
                update(Router)
                .where(Router.id == router_id)
                .values(status="online", last_seen=dt.utcnow())
            )
            await db.commit()
            
            return DeviceStatusResponse(
                online=True,
                details={
                    "identity": identity_data[0].get("name", "Unknown") if identity_data else "Unknown",
                    "uptime": resource_data[0].get("uptime", "0s") if resource_data else "0s",
                    "version": resource_data[0].get("version", "Unknown") if resource_data else "Unknown",
                }
            )
            
        except librouteros.exceptions.ConnectionClosed as e:
            logger.warning(f"Device {router_id} connection closed: {e}")
            return DeviceStatusResponse(
                online=False,
                error="Device not responding - connection closed"
            )
        except librouteros.exceptions.TrapError as e:
            logger.warning(f"Device {router_id} authentication failed: {e}")
            return DeviceStatusResponse(
                online=False,
                error="Authentication failed - invalid credentials"
            )
        except Exception as e:
            logger.warning(f"Device {router_id} connection failed: {e}")
            return DeviceStatusResponse(
                online=False,
                error=f"Connection failed: {str(e)}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check device status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check device status: {str(e)}")

