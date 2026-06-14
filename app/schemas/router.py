"""Router-related Pydantic schemas."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer, model_validator, validator

from app.models.router import RouterStatus, RouterType
from app.core.config import settings


# Helper functions for MikroTik-style formatting
def format_bytes_mikrotik(bytes_value: Optional[int]) -> Optional[str]:
    """Format bytes to MikroTik style (e.g., 128.0MiB, 1.5GiB)."""
    if bytes_value is None:
        return None

    # MikroTik uses binary units (MiB, GiB, KiB)
    if bytes_value >= 1024 * 1024 * 1024:  # GiB
        return f"{bytes_value / (1024 * 1024 * 1024):.1f}GiB"
    elif bytes_value >= 1024 * 1024:  # MiB
        return f"{bytes_value / (1024 * 1024):.1f}MiB"
    elif bytes_value >= 1024:  # KiB
        return f"{bytes_value / 1024:.1f}KiB"
    else:
        return f"{bytes_value}B"


def format_uptime_mikrotik(seconds: Optional[int]) -> Optional[str]:
    """Format uptime to MikroTik style (e.g., 5h18m57s, 2d3h45m)."""
    if seconds is None:
        return None

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return "".join(parts)


def format_frequency_mikrotik(mhz: Optional[int]) -> Optional[str]:
    """Format CPU frequency to MikroTik style (e.g., 600MHz, 1.2GHz)."""
    if mhz is None:
        return None

    if mhz >= 1000:
        return f"{mhz / 1000:.1f}GHz"
    return f"{mhz}MHz"


def format_percentage_mikrotik(value: Optional[int]) -> Optional[str]:
    """Format percentage to MikroTik style (e.g., 5%, 100%)."""
    if value is None:
        return None
    return f"{value}%"


class RouterDeviceBase(BaseModel):
    """Base router device schema."""

    name: str = Field(..., min_length=1, max_length=100)
    device_type: Optional[str] = Field(None, max_length=50)
    mac_address: Optional[str] = Field(None, max_length=17)
    ip_address: Optional[str] = Field(None, max_length=45)
    status: str = Field("active", max_length=20)
    description: Optional[str] = None

    @validator("mac_address")
    def validate_mac_address(cls, v):
        """Validate MAC address format."""
        if v:
            import re
            mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
            if not re.match(mac_pattern, v):
                raise ValueError("Invalid MAC address format")
        return v

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        if v:
            import re
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, v):
                raise ValueError("Invalid IP address format")
        return v


class RouterDeviceCreate(RouterDeviceBase):
    """Schema for creating a router device."""
    pass


class RouterDeviceUpdate(BaseModel):
    """Schema for updating a router device."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    device_type: Optional[str] = Field(None, max_length=50)
    mac_address: Optional[str] = Field(None, max_length=17)
    ip_address: Optional[str] = Field(None, max_length=45)
    status: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = None

    @validator("mac_address")
    def validate_mac_address(cls, v):
        """Validate MAC address format."""
        if v:
            import re
            mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
            if not re.match(mac_pattern, v):
                raise ValueError("Invalid MAC address format")
        return v

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        if v:
            import re
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, v):
                raise ValueError("Invalid IP address format")
        return v


class RouterDevice(RouterDeviceBase):
    """Schema for router device response."""

    id: int
    router_id: int
    last_seen: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RouterBase(BaseModel):
    """Base router schema."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    router_type: RouterType = RouterType.MIKROTIK
    ip_address: str = Field(..., min_length=7, max_length=45)
    port: int = Field(8728, ge=1, le=65535, alias="api_port")
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=255)
    location: Optional[str] = Field(None, max_length=200)
    latitude: Optional[str] = Field(None, max_length=20)
    longitude: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None

    model_config = {"populate_by_name": True}  # Accept both 'port' and 'api_port'

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        import re
        ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        if not re.match(ip_pattern, v):
            raise ValueError("Invalid IP address format")
        return v



class RouterCreate(BaseModel):
    """Schema for creating a router.

    Credentials are NOT sent from frontend. They are automatically pulled from
    environment variables (MIKROTIK_API_USERNAME, MIKROTIK_API_PASSWORD).
    These are the credentials created by the bootstrap script during provisioning.
    """
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    router_type: RouterType = RouterType.MIKROTIK
    ip_address: str = Field(..., min_length=7, max_length=45)
    port: int = Field(8728, ge=1, le=65535, alias="api_port")
    # username and password removed - always pulled from env settings
    location: Optional[str] = Field(None, max_length=200)
    latitude: Optional[str] = Field(None, max_length=20)
    longitude: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None

    model_config = {"populate_by_name": True}  # Accept both 'port' and 'api_port'

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        import re
        ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        if not re.match(ip_pattern, v):
            raise ValueError("Invalid IP address format")
        return v


class RouterUpdate(BaseModel):
    """Schema for updating a router.

    Note: username and password are NOT included here.
    Credentials are managed via the bootstrap provisioning process and stored
    encrypted in the database. API operations pull credentials from the DB.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    ip_address: Optional[str] = Field(None, min_length=7, max_length=45)
    port: Optional[int] = Field(None, ge=1, le=65535)
    # username and password removed - credentials managed via provisioning
    location: Optional[str] = Field(None, max_length=200)
    latitude: Optional[str] = Field(None, max_length=20)
    longitude: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None

    @validator("ip_address")
    def validate_ip_address(cls, v):
        """Validate IP address format."""
        if v:
            import re
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, v):
                raise ValueError("Invalid IP address format")
        return v


class RouterInDB(RouterBase):
    """Schema for router in database (internal use)."""

    id: int
    status: RouterStatus
    is_active: bool
    uptime: int
    last_seen: Optional[datetime] = None
    config: Optional[str] = None

    # System resource information (from /system/resource)
    routeros_version: Optional[str] = None
    board_name: Optional[str] = None
    architecture: Optional[str] = None
    cpu_count: Optional[int] = None
    cpu_frequency: Optional[int] = None
    cpu_load: Optional[int] = None
    total_memory: Optional[int] = None
    free_memory: Optional[int] = None
    total_hdd_space: Optional[int] = None
    free_hdd_space: Optional[int] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Router(BaseModel):
    """Schema for router response (excludes sensitive password field)."""

    id: int
    name: str
    description: Optional[str] = None
    router_type: RouterType
    ip_address: str
    port: int
    username: str
    # password is intentionally excluded from response
    winbox_port: Optional[int] = None  # VPN port for remote Winbox access
    # WireGuard VPN overlay enrollment (vpn_public_key intentionally excluded
    # from the response; vpn_address/vpn_enabled are operational status fields).
    vpn_address: Optional[str] = None
    vpn_enabled: Optional[bool] = None
    location: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    notes: Optional[str] = None
    status: RouterStatus
    is_active: bool
    uptime: int
    last_seen: Optional[datetime] = None
    config: Optional[str] = None

    # System resource information (from /system/resource)
    routeros_version: Optional[str] = None  # e.g., "7.18.2 (stable)"
    board_name: Optional[str] = None  # e.g., "RB951Ui-2HnD"
    architecture: Optional[str] = None  # e.g., "mipsbe"
    cpu_count: Optional[int] = None
    cpu_frequency: Optional[int] = None  # MHz
    cpu_load: Optional[int] = None  # Percentage (0-100)
    total_memory: Optional[int] = None  # Total RAM in bytes
    free_memory: Optional[int] = None  # Free RAM in bytes
    total_hdd_space: Optional[int] = None  # Total storage in bytes
    free_hdd_space: Optional[int] = None  # Free storage in bytes

    # MikroTik-formatted display values (computed from raw values)
    uptime_formatted: Optional[str] = None  # e.g., "5h18m57s"
    cpu_frequency_formatted: Optional[str] = None  # e.g., "600MHz"
    cpu_load_formatted: Optional[str] = None  # e.g., "5%"
    total_memory_formatted: Optional[str] = None  # e.g., "128.0MiB"
    free_memory_formatted: Optional[str] = None  # e.g., "81.1MiB"
    total_hdd_space_formatted: Optional[str] = None  # e.g., "16.0MiB"
    free_hdd_space_formatted: Optional[str] = None  # e.g., "12.5MiB"

    provisioning_status: Optional[str] = None
    bootstrap_completed: Optional[bool] = None
    last_provisioned_at: Optional[datetime] = None
    # Polling-agent liveness (used to derive a real-time status)
    agent_installed: Optional[bool] = None
    agent_poll_interval: Optional[int] = None
    last_poll_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def compute_formatted_fields(self):
        """Compute MikroTik-formatted display values + derive live status.

        The stored `status` field is only as fresh as the last write (the agent
        sets it 'online' on every poll but nothing flips it 'offline' between
        the 5-min Celery sweeps), so a disconnected router would show 'online'
        indefinitely. Derive status here from agent heartbeat freshness so every
        list/detail response reflects reality in real time.
        """
        if self.agent_installed and self.last_poll_at:
            try:
                elapsed = (datetime.utcnow() - self.last_poll_at).total_seconds()
                threshold = (self.agent_poll_interval or 30) * 3
                self.status = (
                    RouterStatus.ONLINE if elapsed < threshold else RouterStatus.OFFLINE
                )
            except Exception:
                pass
        self.uptime_formatted = format_uptime_mikrotik(self.uptime)
        self.cpu_frequency_formatted = format_frequency_mikrotik(self.cpu_frequency)
        self.cpu_load_formatted = format_percentage_mikrotik(self.cpu_load)
        self.total_memory_formatted = format_bytes_mikrotik(self.total_memory)
        self.free_memory_formatted = format_bytes_mikrotik(self.free_memory)
        self.total_hdd_space_formatted = format_bytes_mikrotik(self.total_hdd_space)
        self.free_hdd_space_formatted = format_bytes_mikrotik(self.free_hdd_space)
        return self

    @field_serializer(
        'last_seen', 'last_poll_at', 'last_provisioned_at', 'created_at', 'updated_at',
        when_used='json',
    )
    def _serialize_utc(self, dt: Optional[datetime]):
        """Emit timestamps as explicit UTC so the frontend computes relative time
        correctly. The DB stores naive UTC; without a timezone the browser parses
        them as local time (EAT/UTC+3), which made a fresh poll show
        "Last Seen 3h ago"."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    class Config:
        from_attributes = True


class RouterWithDevices(RouterInDB):
    """Schema for router response with devices (use only with eagerly loaded devices)."""

    devices: List[RouterDevice] = []


class RouterList(BaseModel):
    """Schema for router list response."""

    items: List[Router]
    total: int
    page: int
    size: int
    pages: int


class RouterStats(BaseModel):
    """Schema for router statistics."""

    router_id: int
    router_name: str
    status: str
    uptime: int
    active_subscriptions: int
    total_data_used: int
    last_seen: Optional[datetime] = None


class RouterLog(BaseModel):
    """Schema for router log."""

    id: int
    router_id: int
    action: str
    details: Optional[str] = None
    success: bool
    error_message: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RouterSyncRequest(BaseModel):
    """Schema for router sync request."""

    router_id: int


class RouterSyncResponse(BaseModel):
    """Schema for router sync response."""

    success: bool
    message: str
    router_id: int
    status: Optional[str] = None
    uptime: Optional[int] = None
    last_seen: Optional[datetime] = None
    # System resource fields
    routeros_version: Optional[str] = None
    board_name: Optional[str] = None
    cpu_load: Optional[int] = None
    total_memory: Optional[int] = None
    free_memory: Optional[int] = None

    # MikroTik-formatted display values (computed)
    uptime_formatted: Optional[str] = None
    cpu_load_formatted: Optional[str] = None
    total_memory_formatted: Optional[str] = None
    free_memory_formatted: Optional[str] = None

    @model_validator(mode='after')
    def compute_formatted_fields(self):
        """Compute MikroTik-formatted display values from raw values."""
        self.uptime_formatted = format_uptime_mikrotik(self.uptime)
        self.cpu_load_formatted = format_percentage_mikrotik(self.cpu_load)
        self.total_memory_formatted = format_bytes_mikrotik(self.total_memory)
        self.free_memory_formatted = format_bytes_mikrotik(self.free_memory)
        return self


class WinboxUrlResponse(BaseModel):
    """Schema for Winbox URL response."""

    router_id: int
    router_name: str
    winbox_port: Optional[int] = None
    winbox_url: Optional[str] = None  # Full URL: vpn.domain.com:51255
    local_winbox_url: Optional[str] = None  # Local URL: router_ip:8291
    vpn_domain: str
    is_configured: bool  # True if winbox_port is assigned
    tooltip: str = "Click to copy. Ensure port 8291 is open on the device."
