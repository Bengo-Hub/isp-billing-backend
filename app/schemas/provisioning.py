"""Provisioning schemas for request/response validation."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.provisioning import (
    ProvisioningStatus,
    ProvisioningStep,
    ServiceType,
    ProvisioningPriority
)


# Base schemas
class ProvisioningSessionBase(BaseModel):
    """Base provisioning session schema."""
    
    router_id: int = Field(..., description="Router ID to provision")
    service_type: Optional[ServiceType] = Field(None, description="Service type to configure")
    priority: ProvisioningPriority = Field(ProvisioningPriority.NORMAL, description="Provisioning priority")
    configuration: Optional[Dict[str, Any]] = Field(None, description="Configuration parameters")
    scheduled_at: Optional[datetime] = Field(None, description="Scheduled execution time")
    notes: Optional[str] = Field(None, max_length=1000, description="Additional notes")


class ProvisioningSessionCreate(ProvisioningSessionBase):
    """Provisioning session creation schema."""
    
    # Additional validation for creation
    @field_validator('configuration')
    @classmethod
    def validate_configuration(cls, v):
        """Validate configuration parameters."""
        if v is None:
            return {}
        
        # Basic validation - extend based on service type
        if not isinstance(v, dict):
            raise ValueError("Configuration must be a dictionary")
        
        return v

    @model_validator(mode='after')
    def validate_service_config(self):
        """Validate service type and configuration compatibility."""
        service_type = self.service_type
        config = self.configuration or {}
        
        if service_type == ServiceType.PPPOE_SERVER:
            # Validate PPPoE specific configuration
            if 'interface' not in config and 'default_interface' not in config:
                self.configuration = {**config, 'default_interface': 'ether2'}
        
        elif service_type == ServiceType.HOTSPOT:
            # Validate Hotspot specific configuration
            if 'interface' not in config and 'default_interface' not in config:
                self.configuration = {**config, 'default_interface': 'ether2'}
            if 'ip_pool' not in config:
                self.configuration = {**config, 'ip_pool': '172.31.0.0/16'}
        
        return self


class ProvisioningSessionUpdate(BaseModel):
    """Provisioning session update schema."""
    
    status: Optional[ProvisioningStatus] = None
    current_step: Optional[ProvisioningStep] = None
    progress_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)
    configuration: Optional[Dict[str, Any]] = None
    priority: Optional[ProvisioningPriority] = None
    notes: Optional[str] = Field(None, max_length=1000)
    error_message: Optional[str] = None


class ProvisioningSession(ProvisioningSessionBase):
    """Provisioning session response schema."""
    
    id: int
    session_id: str
    user_id: int
    status: ProvisioningStatus
    current_step: ProvisioningStep
    progress_percentage: float
    success: bool
    error_message: Optional[str]
    rollback_required: bool
    rollback_completed: bool
    ip_address: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    timeout_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProvisioningSessionList(BaseModel):
    """Provisioning session list response."""
    
    items: List[ProvisioningSession]
    total: int
    page: int
    size: int
    pages: int


# Step log schemas
class ProvisioningStepLogBase(BaseModel):
    """Base provisioning step log schema."""
    
    step: ProvisioningStep
    step_order: int
    input_data: Optional[Dict[str, Any]] = None
    sub_steps_total: int = Field(1, ge=1)


class ProvisioningStepLogCreate(ProvisioningStepLogBase):
    """Provisioning step log creation schema."""
    
    session_id: int


class ProvisioningStepLogUpdate(BaseModel):
    """Provisioning step log update schema."""
    
    status: Optional[ProvisioningStatus] = None
    progress_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)
    sub_steps_completed: Optional[int] = Field(None, ge=0)
    output_data: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
    duration_seconds: Optional[float] = Field(None, ge=0.0)


class ProvisioningStepLog(ProvisioningStepLogBase):
    """Provisioning step log response schema."""
    
    id: int
    session_id: int
    status: ProvisioningStatus
    progress_percentage: float
    sub_steps_completed: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    output_data: Optional[Dict[str, Any]]
    error_details: Optional[str]
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Command schemas
class ProvisioningCommandBase(BaseModel):
    """Base provisioning command schema."""
    
    command_type: str = Field(..., description="Command type (script, api_call, config_set)")
    command: str = Field(..., description="The actual command to execute")
    description: Optional[str] = Field(None, max_length=200)
    execution_order: int = Field(..., description="Order of execution")
    rollback_command: Optional[str] = Field(None, description="Command to rollback this operation")
    is_critical: bool = Field(True, description="Whether failure should stop provisioning")
    max_retries: int = Field(3, ge=0, le=10)


class ProvisioningCommandCreate(ProvisioningCommandBase):
    """Provisioning command creation schema."""
    
    session_id: int
    step_log_id: Optional[int] = None


class ProvisioningCommandUpdate(BaseModel):
    """Provisioning command update schema."""
    
    status: Optional[ProvisioningStatus] = None
    output: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = Field(None, ge=0.0)
    success: Optional[bool] = None
    rollback_executed: Optional[bool] = None


class ProvisioningCommand(ProvisioningCommandBase):
    """Provisioning command response schema."""
    
    id: int
    session_id: int
    step_log_id: Optional[int]
    status: ProvisioningStatus
    executed_at: Optional[datetime]
    duration_seconds: Optional[float]
    success: bool
    output: Optional[str]
    error_message: Optional[str]
    rollback_executed: bool
    retry_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Template schemas
class ProvisioningTemplateBase(BaseModel):
    """Base provisioning template schema."""
    
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    version: str = Field("1.0", max_length=20)
    service_type: ServiceType
    router_model: Optional[str] = Field(None, max_length=50)
    min_routeros_version: Optional[str] = Field(None, max_length=20)
    configuration_schema: Dict[str, Any]
    default_configuration: Dict[str, Any]
    command_templates: Dict[str, Any]
    is_active: bool = True
    is_default: bool = False


class ProvisioningTemplateCreate(ProvisioningTemplateBase):
    """Provisioning template creation schema."""
    
    @field_validator('configuration_schema')
    @classmethod
    def validate_schema(cls, v):
        """Validate configuration schema format."""
        if not isinstance(v, dict):
            raise ValueError("Configuration schema must be a dictionary")
        return v

    @field_validator('command_templates')
    @classmethod
    def validate_commands(cls, v):
        """Validate command templates format."""
        if not isinstance(v, dict):
            raise ValueError("Command templates must be a dictionary")
        
        required_steps = ['connection', 'configuration', 'service_setup']
        for step in required_steps:
            if step not in v:
                raise ValueError(f"Command template missing required step: {step}")
        
        return v


class ProvisioningTemplateUpdate(BaseModel):
    """Provisioning template update schema."""
    
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    version: Optional[str] = Field(None, max_length=20)
    service_type: Optional[ServiceType] = None
    router_model: Optional[str] = Field(None, max_length=50)
    min_routeros_version: Optional[str] = Field(None, max_length=20)
    configuration_schema: Optional[Dict[str, Any]] = None
    default_configuration: Optional[Dict[str, Any]] = None
    command_templates: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class ProvisioningTemplate(ProvisioningTemplateBase):
    """Provisioning template response schema."""
    
    id: int
    created_by: int
    usage_count: int
    success_rate: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProvisioningTemplateList(BaseModel):
    """Provisioning template list response."""
    
    items: List[ProvisioningTemplate]
    total: int
    page: int
    size: int
    pages: int


# Configuration schemas
class RouterConfigurationBase(BaseModel):
    """Base router configuration schema."""
    
    configuration_type: str = Field(..., max_length=50)
    configuration_name: Optional[str] = Field(None, max_length=100)
    configuration_data: Dict[str, Any]
    is_backup: bool = False


class RouterConfigurationCreate(RouterConfigurationBase):
    """Router configuration creation schema."""
    
    router_id: int
    session_id: Optional[int] = None


class RouterConfigurationUpdate(BaseModel):
    """Router configuration update schema."""
    
    configuration_name: Optional[str] = Field(None, max_length=100)
    configuration_data: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_backup: Optional[bool] = None


class RouterConfiguration(RouterConfigurationBase):
    """Router configuration response schema."""
    
    id: int
    router_id: int
    session_id: Optional[int]
    is_active: bool
    checksum: Optional[str]
    applied_at: Optional[datetime]
    applied_by: Optional[int]
    rollback_available: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Provisioning workflow schemas
class ProvisioningWorkflowRequest(BaseModel):
    """Complete provisioning workflow request."""
    
    router_id: int
    service_type: ServiceType
    template_id: Optional[int] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
    priority: ProvisioningPriority = ProvisioningPriority.NORMAL
    scheduled_at: Optional[datetime] = None
    auto_start: bool = True
    backup_current_config: bool = True
    rollback_on_failure: bool = True

    @model_validator(mode='after')
    def validate_workflow_config(self):
        """Validate configuration based on service type."""
        service_type = self.service_type
        config = self.configuration or {}
        
        if service_type == ServiceType.HOTSPOT:
            # Validate hotspot configuration
            if 'hotspot_name' not in config:
                config['hotspot_name'] = 'ISP-Hotspot'
            if 'ip_pool_start' not in config:
                config['ip_pool_start'] = '172.31.1.1'
            if 'ip_pool_end' not in config:
                config['ip_pool_end'] = '172.31.1.254'
            if 'gateway' not in config:
                config['gateway'] = '172.31.1.1'
            if 'dns_servers' not in config:
                config['dns_servers'] = ['8.8.8.8', '8.8.4.4']
            if 'interface' not in config:
                config['interface'] = 'ether2'
                
        elif service_type == ServiceType.PPPOE_SERVER:
            # Validate PPPoE configuration
            if 'service_name' not in config:
                config['service_name'] = 'ISP-PPPoE'
            if 'interface' not in config:
                config['interface'] = 'ether2'
            if 'ip_pool_start' not in config:
                config['ip_pool_start'] = '172.31.1.1'
            if 'ip_pool_end' not in config:
                config['ip_pool_end'] = '172.31.1.254'
            if 'dns_servers' not in config:
                config['dns_servers'] = ['8.8.8.8', '8.8.4.4']
        
        self.configuration = config
        return self


class ProvisioningWorkflowResponse(BaseModel):
    """Provisioning workflow response."""
    
    session_id: str
    status: ProvisioningStatus
    message: str
    estimated_duration_minutes: Optional[int] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)


class ProvisioningStatusResponse(BaseModel):
    """Provisioning status response."""
    
    session_id: str
    status: ProvisioningStatus
    current_step: ProvisioningStep
    progress_percentage: float
    steps_completed: int
    steps_total: int
    estimated_time_remaining_minutes: Optional[int] = None
    current_operation: Optional[str] = None
    error_message: Optional[str] = None
    can_cancel: bool = True
    can_retry: bool = False


class ProvisioningCancelRequest(BaseModel):
    """Provisioning cancellation request."""
    
    reason: Optional[str] = Field(None, max_length=500)
    force_cancel: bool = False
    cleanup_partial_config: bool = True


class ProvisioningRetryRequest(BaseModel):
    """Provisioning retry request."""
    
    from_step: Optional[ProvisioningStep] = None
    reset_configuration: bool = False
    updated_configuration: Optional[Dict[str, Any]] = None
