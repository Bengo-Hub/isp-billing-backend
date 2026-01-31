"""
WebSocket endpoints for live streaming of provisioning logs.
Provides real-time updates during the provisioning process.
"""
import logging
import json
import asyncio
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.websockets import WebSocketState
from app.modules.provisioning import ProvisioningService

logger = logging.getLogger(__name__)
router = APIRouter()

# Store active WebSocket connections by session_id
active_connections: Dict[str, Set[WebSocket]] = {}


class ConnectionManager:
    """Manages WebSocket connections for provisioning sessions."""
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a WebSocket connection and add it to the session."""
        await websocket.accept()
        
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        
        self.active_connections[session_id].add(websocket)
        logger.info(f"WebSocket connected for session {session_id}")
    
    def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a WebSocket connection from the session."""
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            
            # Clean up empty session
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        
        logger.info(f"WebSocket disconnected for session {session_id}")
    
    async def send_message(self, session_id: str, message: dict):
        """Send a message to all connected clients for a session."""
        if session_id in self.active_connections:
            # Create a copy of the set to avoid modification during iteration
            connections = self.active_connections[session_id].copy()
            
            for websocket in connections:
                try:
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_text(json.dumps(message))
                    else:
                        # Remove disconnected websockets
                        self.active_connections[session_id].discard(websocket)
                except Exception as e:
                    logger.error(f"Error sending message to WebSocket: {e}")
                    self.active_connections[session_id].discard(websocket)
    
    async def broadcast_log(self, session_id: str, log_entry: dict):
        """Broadcast a log entry to all connected clients."""
        message = {
            "type": "log",
            "session_id": session_id,
            "data": log_entry
        }
        await self.send_message(session_id, message)
    
    async def broadcast_status(self, session_id: str, status: dict):
        """Broadcast status update to all connected clients."""
        message = {
            "type": "status",
            "session_id": session_id,
            "data": status
        }
        await self.send_message(session_id, message)


# Global connection manager instance
manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for live provisioning updates."""
    await manager.connect(websocket, session_id)
    
    try:
        while True:
            # Keep the connection alive and handle any incoming messages
            data = await websocket.receive_text()
            
            # Handle client messages if needed
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")
        manager.disconnect(websocket, session_id)


# Function to broadcast provisioning updates (called by ProvisioningService)
async def broadcast_provisioning_update(session_id: str, update_type: str, data: dict):
    """Broadcast provisioning updates to connected WebSocket clients."""
    if update_type == "log":
        await manager.broadcast_log(session_id, data)
    elif update_type == "status":
        await manager.broadcast_status(session_id, data)
    elif update_type == "provisioning_complete":
        # Send a dedicated provisioning_complete message type for frontend redirect
        message = {
            "type": "provisioning_complete",
            "session_id": session_id,
            "data": data
        }
        await manager.send_message(session_id, message)


# Function to broadcast router logs (called by router monitoring)
async def broadcast_router_log(session_id: str, router_log: dict):
    """Broadcast router logs to connected WebSocket clients."""
    message = {
        "type": "router_log",
        "session_id": session_id,
        "data": router_log
    }
    await manager.send_message(session_id, message)
