"""Pydantic schemas for router agent polling endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---- Poll Request/Response ----

class AgentPollRequest(BaseModel):
    """Telemetry payload sent by router agent on each poll."""

    router_id: int = Field(..., description="Router DB ID")
    version: str = Field("", description="RouterOS version")
    uptime: str = Field("", description="Router uptime string")
    cpu_load: int = Field(0, ge=0, le=100, description="CPU load percentage")
    free_memory: int = Field(0, ge=0, description="Free memory in bytes")
    total_memory: int = Field(0, ge=0, description="Total memory in bytes")
    free_hdd_space: int = Field(0, ge=0, description="Free storage in bytes")
    total_hdd_space: int = Field(0, ge=0, description="Total storage in bytes")
    active_pppoe: int = Field(0, ge=0, description="Active PPPoE sessions")
    active_hotspot: int = Field(0, ge=0, description="Active hotspot sessions")


class AgentCommand(BaseModel):
    """A command for the router to execute."""

    id: str
    action: str
    params: Dict[str, Any] = {}


class AgentPollResponse(BaseModel):
    """Response to a router poll — pending commands to execute."""

    commands: List[AgentCommand] = []
    poll_interval: int = 30
    agent_version: str = "1.0"


# ---- Report Request/Response ----

class CommandResult(BaseModel):
    """Result of a single command execution on the router."""

    id: str = Field(..., description="Command UUID")
    status: str = Field(..., description="success or failed")
    message: str = Field("", description="Optional result message or error")


class AgentReportRequest(BaseModel):
    """Command execution results reported by router agent."""

    router_id: int
    results: List[CommandResult]


class AgentReportResponse(BaseModel):
    """Acknowledgement of report receipt."""

    ok: bool = True
    processed: int = 0


# ---- Command Queue Status (for admin dashboard) ----

class RouterCommandStatus(BaseModel):
    """Status of a queued router command."""

    id: str
    action: str
    params: Dict[str, Any] = {}
    priority: int = 5
    status: str
    created_at: Optional[str] = None
    sent_at: Optional[str] = None
    completed_at: Optional[str] = None
    result_message: Optional[str] = None
    retry_count: int = 0
    source: Optional[str] = None

    class Config:
        from_attributes = True


class RouterAgentStatus(BaseModel):
    """Agent status summary for a router."""

    router_id: int
    agent_installed: bool = False
    agent_version: Optional[str] = None
    last_poll_at: Optional[str] = None
    poll_interval: int = 30
    is_online: bool = False
    pending_commands: int = 0
