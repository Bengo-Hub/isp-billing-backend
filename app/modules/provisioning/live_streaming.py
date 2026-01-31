"""
Live streaming functionality for provisioning sessions.
Handles real-time communication between backend and frontend.
"""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LiveStreamingManager:
    """Manages live streaming of provisioning updates."""
    
    def __init__(self):
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
    
    async def start_session(self, session_id: str, router_id: int):
        """Start live streaming for a provisioning session."""
        self.active_sessions[session_id] = {
            'router_id': router_id,
            'started_at': datetime.now(timezone.utc),
            'status': 'running'
        }
        
        await self.broadcast_log(session_id, {
            'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'message': 'Provisioning session started',
            'level': 'info'
        })
    
    async def end_session(self, session_id: str, success: bool = True):
        """End live streaming for a provisioning session."""
        if session_id in self.active_sessions:
            self.active_sessions[session_id]['status'] = 'completed' if success else 'failed'
            self.active_sessions[session_id]['ended_at'] = datetime.now(timezone.utc)

            await self.broadcast_log(session_id, {
                'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                'message': f'Provisioning session {"completed successfully" if success else "failed"}',
                'level': 'success' if success else 'error'
            })

            # Broadcast provisioning complete event for frontend redirect
            if success:
                await self.broadcast_provisioning_complete(session_id)

    async def broadcast_provisioning_complete(self, session_id: str):
        """Broadcast provisioning complete event to trigger frontend redirect."""
        try:
            from app.api.v1.provisioning.stream import broadcast_provisioning_update
            await broadcast_provisioning_update(session_id, 'provisioning_complete', {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'message': 'Provisioning completed successfully! Router is now ready.',
                'success': True
            })
            logger.info(f"Broadcasted provisioning complete for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to broadcast provisioning complete for session {session_id}: {e}")
    
    async def broadcast_log(self, session_id: str, log_entry: Dict[str, Any]):
        """Broadcast a log entry to connected clients."""
        try:
            # Lazy import to avoid circular dependency
            from app.api.v1.provisioning.stream import broadcast_provisioning_update
            await broadcast_provisioning_update(session_id, 'log', log_entry)
            logger.info(f"Broadcasted log for session {session_id}: {log_entry.get('message', '')}")
        except Exception as e:
            logger.error(f"Failed to broadcast log for session {session_id}: {e}")
    
    async def broadcast_status(self, session_id: str, status_data: Dict[str, Any]):
        """Broadcast status update to connected clients."""
        try:
            # Lazy import to avoid circular dependency
            from app.api.v1.provisioning.stream import broadcast_provisioning_update
            await broadcast_provisioning_update(session_id, 'status', status_data)
            logger.info(f"Broadcasted status for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to broadcast status for session {session_id}: {e}")
    
    async def broadcast_router_log(self, session_id: str, router_log: Dict[str, Any]):
        """Broadcast router log to connected clients."""
        try:
            # Lazy import to avoid circular dependency
            from app.api.v1.provisioning.stream import broadcast_router_log as broadcast_router_log_func
            await broadcast_router_log_func(session_id, router_log)
            logger.info(f"Broadcasted router log for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to broadcast router log for session {session_id}: {e}")
    
    async def log_provisioning_step(self, session_id: str, step: str, message: str, level: str = 'info'):
        """Log a provisioning step with live streaming."""
        log_entry = {
            'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'message': message,
            'level': level,
            'step': step
        }
        
        await self.broadcast_log(session_id, log_entry)
        
        # Also log to standard logging
        log_method = getattr(logger, level, logger.info)
        log_method(f"Provisioning session {session_id} - {step}: {message}")
    
    async def update_progress(self, session_id: str, progress_percentage: float, current_operation: str):
        """Update provisioning progress with live streaming."""
        status_data = {
            'progress_percentage': progress_percentage,
            'current_operation': current_operation,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        await self.broadcast_status(session_id, status_data)
    
    async def stream_router_output(self, session_id: str, router_output: str):
        """Stream router output to connected clients."""
        # Parse router output and broadcast relevant logs
        lines = router_output.strip().split('\n')
        
        for line in lines:
            if line.strip():
                await self.broadcast_router_log(session_id, {
                    'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                    'message': line.strip(),
                    'source': 'router'
                })
                
                # Small delay to avoid overwhelming the client
                await asyncio.sleep(0.1)


# Global streaming manager instance
streaming_manager = LiveStreamingManager()
