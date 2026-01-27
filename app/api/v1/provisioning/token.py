"""Provisioning Token Management endpoints.

Provides automatic token regeneration when authentication fails.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict
import logging

from app.core.database import get_db
from app.core.security import create_access_token
from app.api.deps import get_current_user
from app.models.provisioning import ProvisioningSession
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/regenerate-token/{session_id}")
async def regenerate_provisioning_token(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict:
    """Regenerate provisioning token when authentication fails.
    
    This endpoint is called automatically when the provisioning workflow
    detects an authentication failure. It generates a new token and
    updates the session record.
    
    Args:
        session_id: The provisioning session ID
        background_tasks: FastAPI background tasks
        current_user: The authenticated user
        db: Database session
        
    Returns:
        Dict with new_token, session_id, and updated bootstrap_command
    """
    try:
        # Fetch the session
        session = db.query(ProvisioningSession).filter(
            ProvisioningSession.id == session_id
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="Provisioning session not found")
        
        # Verify ownership
        if session.user_id != current_user.id:
            raise HTTPException(
                status_code=403, 
                detail="Not authorized to regenerate token for this session"
            )
        
        # Generate new token with permissions
        new_token = create_access_token(
            data={
                "sub": str(current_user.id),
                "permissions": ["provisioning:read", "provisioning:write"]
            },
            token_type="access"
        )
        
        # Update the session
        session.provisioning_token = new_token
        
        # Regenerate bootstrap command with new token
        from app.api.v1.provisioning.bootstrap import get_bootstrap_command
        
        command_response = await get_bootstrap_command(
            router_id=session.router_id,
            db=db,
            current_user=current_user
        )
        
        session.bootstrap_command = command_response["command"]
        db.commit()
        
        logger.info(
            f"Regenerated provisioning token for session {session_id} "
            f"(user: {current_user.id})"
        )
        
        # Broadcast update to WebSocket clients
        background_tasks.add_task(
            broadcast_token_update,
            session_id=session_id,
            new_token=new_token,
            new_command=command_response["command"]
        )
        
        return {
            "new_token": new_token,
            "session_id": session_id,
            "bootstrap_command": command_response["command"],
            "message": "Token regenerated successfully. Please use the new bootstrap command."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating token for session {session_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to regenerate token: {str(e)}"
        )


async def broadcast_token_update(session_id: str, new_token: str, new_command: str):
    """Broadcast token update to connected WebSocket clients.
    
    Args:
        session_id: The provisioning session ID
        new_token: The newly generated token
        new_command: The updated bootstrap command
    """
    from app.api.v1.provisioning.stream import manager
    
    try:
        await manager.broadcast_provisioning_update(
            session_id=session_id,
            update={
                "type": "token_regenerated",
                "new_token": new_token,
                "bootstrap_command": new_command,
                "message": "Authentication failed. A new token has been generated. Please copy the new bootstrap command and run it on your device.",
                "action_required": True
            }
        )
        logger.info(f"Broadcasted token update for session {session_id}")
    except Exception as e:
        logger.error(f"Failed to broadcast token update for session {session_id}: {e}")
