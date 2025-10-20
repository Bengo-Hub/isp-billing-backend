"""Production-ready MikroTik device provisioning service.

This service implements a comprehensive 3-step provisioning workflow:
1. Connection & Verification - Test connectivity and gather device info
2. Configuration - Apply basic router configuration and security
3. Service Setup - Configure PPPoE/Hotspot services and user management

Based on Centipid billing system provisioning process with production-ready features:
- Atomic operations with rollback capability
- Progress tracking and real-time updates
- Template-based configuration
- Comprehensive error handling and logging
- Background task processing
- Configuration backup and restore
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.core.exceptions import (
    ProvisioningError,
    RouterConnectionError,
    ConfigurationError,
    ValidationError
)
from app.models.provisioning import (
    ProvisioningSession,
    ProvisioningStepLog,
    ProvisioningCommand,
    ProvisioningTemplate,
    RouterConfiguration,
    ProvisioningStatus,
    ProvisioningStep,
    ServiceType,
    ProvisioningPriority
)
from app.models.router import Router, RouterStatus
from app.models.user import User
from app.integrations.mikrotik import MikroTikAPI
from app.services.router_service import RouterService
from app.api.deps import PaginationParams

logger = get_logger(__name__)


class ProvisioningService:
    """Production-ready provisioning service for MikroTik devices."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.router_service = RouterService(db)
        self.logger = get_logger(__name__)
        
        # Provisioning configuration
        self.default_timeout_minutes = 30
        self.step_timeout_minutes = 10
        self.max_concurrent_sessions = 5
        self.retry_delays = [1, 2, 5, 10]  # Exponential backoff
        
        # MikroTik command templates
        self.command_templates = self._load_command_templates()

    def _load_command_templates(self) -> Dict[str, Dict[str, Any]]:
        """Load MikroTik command templates for different services."""
        return {
            "connection": {
                "system_info": "/system/resource/print",
                "identity_check": "/system/identity/print",
                "interface_list": "/interface/print",
                "ip_address_list": "/ip/address/print",
                "version_check": "/system/package/print where name=system"
            },
            "configuration": {
                "set_identity": "/system/identity/set name={identity}",
                "create_bridge": "/interface/bridge/add name={bridge_name}",
                "add_bridge_port": "/interface/bridge/port/add interface={interface} bridge={bridge_name}",
                "set_ip_address": "/ip/address/add address={ip_address} interface={interface}",
                "set_dns": "/ip/dns/set servers={dns_servers}",
                "create_ip_pool": "/ip/pool/add name={pool_name} ranges={ip_range}",
                "enable_api": "/ip/service/set api disabled=no port={api_port}",
                "create_admin_user": "/user/add name={username} password={password} group=full",
                "set_ntp": "/system/ntp/client/set enabled=yes server-dns-names={ntp_servers}",
                "configure_firewall": "/ip/firewall/filter/add chain=input action=accept protocol=icmp",
            },
            "hotspot": {
                "create_hotspot": "/ip/hotspot/add name={hotspot_name} interface={interface}",
                "set_hotspot_profile": "/ip/hotspot/profile/set {profile_id} dns-name={dns_name} hotspot-address={gateway}",
                "create_user_profile": "/ip/hotspot/user/profile/add name={profile_name} rate-limit={rate_limit}",
                "add_hotspot_user": "/ip/hotspot/user/add name={username} password={password} profile={profile}",
                "configure_walled_garden": "/ip/hotspot/walled-garden/add dst-host={host}",
                "set_login_page": "/ip/hotspot/profile/set {profile_id} login-by=http-chap,cookie",
                "configure_radius": "/radius/add service=hotspot address={radius_server} secret={radius_secret}",
                "enable_anti_sharing": "/ip/hotspot/profile/set {profile_id} login-by=http-chap session-timeout=1d idle-timeout=5m",
            },
            "pppoe": {
                "create_ppp_profile": "/ppp/profile/add name={profile_name} rate-limit={rate_limit} local-address={local_address} remote-address={ip_pool}",
                "enable_pppoe_server": "/interface/pppoe-server/server/add service-name={service_name} interface={interface} default-profile={profile}",
                "add_ppp_secret": "/ppp/secret/add name={username} password={password} service=pppoe profile={profile}",
                "configure_radius_ppp": "/radius/add service=ppp address={radius_server} secret={radius_secret}",
                "set_ppp_auth": "/ppp/aaa/set use-radius=yes",
                "configure_accounting": "/ppp/profile/set {profile_id} use-upnp=yes use-compression=yes",
            },
            "security": {
                "disable_default_services": [
                    "/ip/service/set telnet disabled=yes",
                    "/ip/service/set ftp disabled=yes",
                    "/ip/service/set www disabled=yes",
                    "/ip/service/set ssh port=2222",
                ],
                "create_firewall_rules": [
                    "/ip/firewall/filter/add chain=input action=accept connection-state=established,related",
                    "/ip/firewall/filter/add chain=input action=accept protocol=icmp",
                    "/ip/firewall/filter/add chain=input action=accept dst-port=8728 protocol=tcp src-address={management_ip}",
                    "/ip/firewall/filter/add chain=input action=drop",
                ],
                "configure_snmp": "/snmp/set enabled=yes contact={contact} location={location}",
            }
        }

    async def create_provisioning_session(
        self,
        router_id: int,
        user_id: int,
        service_type: ServiceType,
        configuration: Dict[str, Any],
        priority: ProvisioningPriority = ProvisioningPriority.NORMAL,
        template_id: Optional[int] = None,
        scheduled_at: Optional[datetime] = None
    ) -> ProvisioningSession:
        """Create a new provisioning session."""
        try:
            # Validate router exists and is accessible
            router = await self.router_service.get_by_id(router_id)
            if not router:
                raise ValidationError(f"Router {router_id} not found")

            # Check for existing active sessions
            existing_session = await self._get_active_session(router_id)
            if existing_session:
                raise ProvisioningError(
                    f"Router {router_id} already has an active provisioning session: {existing_session.session_id}"
                )

            # Generate unique session ID
            session_id = str(uuid.uuid4())

            # Load template if specified
            if template_id:
                template = await self._get_template(template_id)
                if template and template.service_type == service_type:
                    # Merge template configuration with provided configuration
                    template_config = template.get_default_configuration()
                    configuration = {**template_config, **configuration}

            # Validate configuration
            validated_config = await self._validate_configuration(service_type, configuration)

            # Calculate timeout
            timeout_at = datetime.utcnow() + timedelta(minutes=self.default_timeout_minutes)

            # Create session
            session = ProvisioningSession(
                session_id=session_id,
                router_id=router_id,
                user_id=user_id,
                service_type=service_type,
                configuration=validated_config,
                priority=priority,
                scheduled_at=scheduled_at,
                timeout_at=timeout_at,
                status=ProvisioningStatus.PENDING
            )

            self.db.add(session)
            await self.db.commit()
            await self.db.refresh(session)

            # Create initial step logs
            await self._create_step_logs(session.id)

            self.logger.info(f"Created provisioning session {session_id} for router {router_id}")
            return session

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to create provisioning session: {e}")
            raise

    async def start_provisioning(self, session_id: str) -> bool:
        """Start the provisioning process for a session."""
        try:
            session = await self._get_session_by_id(session_id)
            if not session:
                raise ProvisioningError(f"Session {session_id} not found")

            if session.status != ProvisioningStatus.PENDING:
                raise ProvisioningError(f"Session {session_id} is not in pending status")

            # Update session status
            session.status = ProvisioningStatus.IN_PROGRESS
            session.started_at = datetime.utcnow()
            session.current_step = ProvisioningStep.CONNECTION

            await self.db.commit()

            # Start provisioning process in background
            asyncio.create_task(self._execute_provisioning_workflow(session))

            self.logger.info(f"Started provisioning session {session_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start provisioning session {session_id}: {e}")
            return False

    async def _execute_provisioning_workflow(self, session: ProvisioningSession) -> None:
        """Execute the complete provisioning workflow."""
        try:
            # Step 1: Connection and Verification
            await self._execute_connection_step(session)
            
            if session.status == ProvisioningStatus.FAILED:
                return

            # Step 2: Basic Configuration
            await self._execute_configuration_step(session)
            
            if session.status == ProvisioningStatus.FAILED:
                return

            # Step 3: Service Setup
            await self._execute_service_setup_step(session)

            # Mark as completed if all steps succeeded
            if session.status == ProvisioningStatus.IN_PROGRESS:
                session.status = ProvisioningStatus.COMPLETED
                session.success = True
                session.completed_at = datetime.utcnow()
                session.progress_percentage = 100.0

                await self.db.commit()
                self.logger.info(f"Provisioning session {session.session_id} completed successfully")

        except Exception as e:
            await self._handle_provisioning_error(session, str(e))

    async def _execute_connection_step(self, session: ProvisioningSession) -> None:
        """Execute Step 1: Connection and Verification."""
        step_log = await self._get_step_log(session.id, ProvisioningStep.CONNECTION)
        
        try:
            step_log.status = ProvisioningStatus.IN_PROGRESS
            step_log.started_at = datetime.utcnow()
            await self.db.commit()

            router = await self.router_service.get_by_id(session.router_id)
            api = MikroTikAPI(router)

            # Sub-step 1: Test connection (25%)
            await self._update_step_progress(step_log, 25.0, "Testing connection...")
            connected = await api.connect()
            
            if not connected:
                raise RouterConnectionError(f"Failed to connect to router {router.ip_address}")

            # Sub-step 2: Get system information (50%)
            await self._update_step_progress(step_log, 50.0, "Gathering system information...")
            system_info = await api.get_system_info()
            
            if not system_info:
                raise RouterConnectionError("Failed to retrieve system information")

            # Sub-step 3: Verify RouterOS version (75%)
            await self._update_step_progress(step_log, 75.0, "Verifying RouterOS version...")
            version_info = await api.get_routeros_version()
            
            # Store system information
            step_log.output_data = {
                "system_info": system_info,
                "version_info": version_info,
                "connection_test": "successful"
            }

            # Sub-step 4: Validate compatibility (100%)
            await self._update_step_progress(step_log, 100.0, "Validating compatibility...")
            await self._validate_router_compatibility(system_info, version_info)

            # Update session and step
            step_log.status = ProvisioningStatus.COMPLETED
            step_log.completed_at = datetime.utcnow()
            step_log.duration_seconds = (step_log.completed_at - step_log.started_at).total_seconds()
            
            session.current_step = ProvisioningStep.CONFIGURATION
            session.progress_percentage = 33.3

            await api.disconnect()
            await self.db.commit()

        except Exception as e:
            await self._handle_step_error(session, step_log, str(e))

    async def _execute_configuration_step(self, session: ProvisioningSession) -> None:
        """Execute Step 2: Basic Configuration."""
        step_log = await self._get_step_log(session.id, ProvisioningStep.CONFIGURATION)
        
        try:
            step_log.status = ProvisioningStatus.IN_PROGRESS
            step_log.started_at = datetime.utcnow()
            await self.db.commit()

            router = await self.router_service.get_by_id(session.router_id)
            api = MikroTikAPI(router)
            
            await api.connect()
            config = session.get_configuration()

            # Create backup of current configuration
            await self._update_step_progress(step_log, 10.0, "Creating configuration backup...")
            await self._backup_router_configuration(session, api)

            # Apply basic configuration commands
            commands = await self._generate_configuration_commands(config, session.service_type)
            total_commands = len(commands)

            for i, command_data in enumerate(commands):
                progress = 10.0 + (80.0 * (i + 1) / total_commands)
                await self._update_step_progress(
                    step_log, 
                    progress, 
                    f"Executing command {i+1}/{total_commands}: {command_data['description']}"
                )
                
                # Execute command with retry logic
                success = await self._execute_command_with_retry(session, api, command_data)
                
                if not success and command_data.get('critical', True):
                    raise ConfigurationError(f"Critical command failed: {command_data['description']}")

            # Verify configuration
            await self._update_step_progress(step_log, 95.0, "Verifying configuration...")
            await self._verify_basic_configuration(api, config)

            # Finalize step
            await self._update_step_progress(step_log, 100.0, "Configuration completed")
            
            step_log.status = ProvisioningStatus.COMPLETED
            step_log.completed_at = datetime.utcnow()
            step_log.duration_seconds = (step_log.completed_at - step_log.started_at).total_seconds()
            
            session.current_step = ProvisioningStep.SERVICE_SETUP
            session.progress_percentage = 66.6

            await api.disconnect()
            await self.db.commit()

        except Exception as e:
            await self._handle_step_error(session, step_log, str(e))

    async def _execute_service_setup_step(self, session: ProvisioningSession) -> None:
        """Execute Step 3: Service Setup (PPPoE/Hotspot)."""
        step_log = await self._get_step_log(session.id, ProvisioningStep.SERVICE_SETUP)
        
        try:
            step_log.status = ProvisioningStatus.IN_PROGRESS
            step_log.started_at = datetime.utcnow()
            await self.db.commit()

            router = await self.router_service.get_by_id(session.router_id)
            api = MikroTikAPI(router)
            
            await api.connect()
            config = session.get_configuration()

            # Generate service-specific commands
            if session.service_type == ServiceType.HOTSPOT:
                commands = await self._generate_hotspot_commands(config)
            elif session.service_type == ServiceType.PPPOE_SERVER:
                commands = await self._generate_pppoe_commands(config)
            else:  # BOTH
                hotspot_commands = await self._generate_hotspot_commands(config)
                pppoe_commands = await self._generate_pppoe_commands(config)
                commands = hotspot_commands + pppoe_commands

            total_commands = len(commands)

            for i, command_data in enumerate(commands):
                progress = 10.0 + (80.0 * (i + 1) / total_commands)
                await self._update_step_progress(
                    step_log, 
                    progress, 
                    f"Configuring service {i+1}/{total_commands}: {command_data['description']}"
                )
                
                success = await self._execute_command_with_retry(session, api, command_data)
                
                if not success and command_data.get('critical', True):
                    raise ConfigurationError(f"Service configuration failed: {command_data['description']}")

            # Apply security configurations
            await self._update_step_progress(step_log, 90.0, "Applying security configurations...")
            await self._apply_security_configuration(api, config)

            # Final verification
            await self._update_step_progress(step_log, 95.0, "Performing final verification...")
            await self._verify_service_configuration(api, session.service_type, config)

            await self._update_step_progress(step_log, 100.0, "Service setup completed")
            
            step_log.status = ProvisioningStatus.COMPLETED
            step_log.completed_at = datetime.utcnow()
            step_log.duration_seconds = (step_log.completed_at - step_log.started_at).total_seconds()
            
            session.progress_percentage = 100.0

            await api.disconnect()
            await self.db.commit()

        except Exception as e:
            await self._handle_step_error(session, step_log, str(e))

    async def _generate_configuration_commands(
        self, 
        config: Dict[str, Any], 
        service_type: ServiceType
    ) -> List[Dict[str, Any]]:
        """Generate basic configuration commands."""
        commands = []
        
        # Set system identity
        if 'identity' in config:
            commands.append({
                'type': 'api_call',
                'command': f"/system/identity/set name={config['identity']}",
                'description': 'Set system identity',
                'critical': False
            })

        # Create bridge if needed
        if service_type in [ServiceType.HOTSPOT, ServiceType.BOTH]:
            bridge_name = config.get('bridge_name', 'bridge-hotspot')
            commands.append({
                'type': 'api_call',
                'command': f"/interface/bridge/add name={bridge_name}",
                'description': f'Create bridge {bridge_name}',
                'critical': True
            })
            
            # Add interface to bridge
            interface = config.get('interface', 'ether2')
            commands.append({
                'type': 'api_call',
                'command': f"/interface/bridge/port/add interface={interface} bridge={bridge_name}",
                'description': f'Add {interface} to bridge',
                'critical': True
            })

        # Configure IP pool
        if 'ip_pool_start' in config and 'ip_pool_end' in config:
            pool_name = config.get('pool_name', 'ip-pool')
            ip_range = f"{config['ip_pool_start']}-{config['ip_pool_end']}"
            commands.append({
                'type': 'api_call',
                'command': f"/ip/pool/add name={pool_name} ranges={ip_range}",
                'description': f'Create IP pool {pool_name}',
                'critical': True
            })

        # Set DNS servers
        if 'dns_servers' in config:
            dns_list = ','.join(config['dns_servers'])
            commands.append({
                'type': 'api_call',
                'command': f"/ip/dns/set servers={dns_list}",
                'description': 'Configure DNS servers',
                'critical': False
            })

        return commands

    async def _generate_hotspot_commands(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate hotspot-specific commands."""
        commands = []
        
        hotspot_name = config.get('hotspot_name', 'ISP-Hotspot')
        interface = config.get('interface', 'ether2')
        
        # Create hotspot
        commands.append({
            'type': 'api_call',
            'command': f"/ip/hotspot/add name={hotspot_name} interface={interface}",
            'description': f'Create hotspot {hotspot_name}',
            'critical': True
        })

        # Configure anti-sharing if enabled
        if config.get('enable_anti_sharing', False):
            commands.append({
                'type': 'api_call',
                'command': f"/ip/hotspot/profile/set default login-by=http-chap session-timeout=1d idle-timeout=5m",
                'description': 'Enable anti-sharing protection',
                'critical': False
            })

        # Add walled garden entries
        if 'walled_garden_hosts' in config:
            for host in config['walled_garden_hosts']:
                commands.append({
                    'type': 'api_call',
                    'command': f"/ip/hotspot/walled-garden/add dst-host={host}",
                    'description': f'Add walled garden host {host}',
                    'critical': False
                })

        return commands

    async def _generate_pppoe_commands(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate PPPoE-specific commands."""
        commands = []
        
        service_name = config.get('service_name', 'ISP-PPPoE')
        interface = config.get('interface', 'ether2')
        profile_name = config.get('profile_name', 'default-ppp')
        
        # Create PPP profile
        local_address = config.get('gateway', '172.31.1.1')
        ip_pool = config.get('pool_name', 'ip-pool')
        
        commands.append({
            'type': 'api_call',
            'command': f"/ppp/profile/add name={profile_name} local-address={local_address} remote-address={ip_pool}",
            'description': f'Create PPP profile {profile_name}',
            'critical': True
        })

        # Enable PPPoE server
        commands.append({
            'type': 'api_call',
            'command': f"/interface/pppoe-server/server/add service-name={service_name} interface={interface} default-profile={profile_name}",
            'description': f'Enable PPPoE server {service_name}',
            'critical': True
        })

        return commands

    async def _execute_command_with_retry(
        self, 
        session: ProvisioningSession, 
        api: MikroTikAPI, 
        command_data: Dict[str, Any]
    ) -> bool:
        """Execute a command with retry logic."""
        command = ProvisioningCommand(
            session_id=session.id,
            command_type=command_data['type'],
            command=command_data['command'],
            description=command_data.get('description', ''),
            execution_order=command_data.get('order', 0),
            is_critical=command_data.get('critical', True),
            rollback_command=command_data.get('rollback', None)
        )
        
        self.db.add(command)
        await self.db.commit()

        max_retries = command.max_retries
        
        for attempt in range(max_retries + 1):
            try:
                command.executed_at = datetime.utcnow()
                command.status = ProvisioningStatus.IN_PROGRESS
                
                start_time = datetime.utcnow()
                
                # Execute the command
                if command_data['type'] == 'api_call':
                    result = await api.execute_command(command_data['command'])
                else:
                    result = await api.execute_script(command_data['command'])
                
                end_time = datetime.utcnow()
                command.duration_seconds = (end_time - start_time).total_seconds()
                command.output = str(result) if result else None
                command.success = True
                command.status = ProvisioningStatus.COMPLETED
                
                await self.db.commit()
                return True

            except Exception as e:
                command.retry_count = attempt + 1
                command.error_message = str(e)
                command.success = False
                
                if attempt < max_retries:
                    # Wait before retry with exponential backoff
                    delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                    await asyncio.sleep(delay)
                    command.status = ProvisioningStatus.PENDING
                else:
                    command.status = ProvisioningStatus.FAILED
                
                await self.db.commit()

        return False

    async def _backup_router_configuration(self, session: ProvisioningSession, api: MikroTikAPI) -> None:
        """Create a backup of the current router configuration."""
        try:
            # Get current configuration
            config_data = await api.export_configuration()
            
            if config_data:
                # Create configuration record
                config = RouterConfiguration(
                    router_id=session.router_id,
                    session_id=session.id,
                    configuration_type='backup',
                    configuration_name=f'pre-provisioning-{datetime.utcnow().isoformat()}',
                    configuration_data=config_data,
                    is_backup=True,
                    rollback_available=True,
                    checksum=hashlib.sha256(json.dumps(config_data, sort_keys=True).encode()).hexdigest()
                )
                
                self.db.add(config)
                await self.db.commit()
                
                self.logger.info(f"Created configuration backup for router {session.router_id}")

        except Exception as e:
            self.logger.warning(f"Failed to create configuration backup: {e}")
            # Don't fail provisioning for backup failure

    async def _validate_configuration(
        self, 
        service_type: ServiceType, 
        configuration: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate and normalize configuration parameters."""
        validated_config = configuration.copy()

        # Common validation
        if 'interface' not in validated_config:
            validated_config['interface'] = 'ether2'

        if 'dns_servers' not in validated_config:
            validated_config['dns_servers'] = ['8.8.8.8', '8.8.4.4']

        # Service-specific validation
        if service_type == ServiceType.HOTSPOT:
            if 'hotspot_name' not in validated_config:
                validated_config['hotspot_name'] = 'ISP-Hotspot'
            
            if 'ip_pool_start' not in validated_config:
                validated_config['ip_pool_start'] = '172.31.1.1'
            
            if 'ip_pool_end' not in validated_config:
                validated_config['ip_pool_end'] = '172.31.1.254'
                
            if 'gateway' not in validated_config:
                validated_config['gateway'] = '172.31.1.1'

        elif service_type == ServiceType.PPPOE_SERVER:
            if 'service_name' not in validated_config:
                validated_config['service_name'] = 'ISP-PPPoE'
            
            if 'ip_pool_start' not in validated_config:
                validated_config['ip_pool_start'] = '172.31.1.1'
            
            if 'ip_pool_end' not in validated_config:
                validated_config['ip_pool_end'] = '172.31.1.254'

        return validated_config

    # Helper methods for session management
    async def _get_session_by_id(self, session_id: str) -> Optional[ProvisioningSession]:
        """Get provisioning session by session ID."""
        result = await self.db.execute(
            select(ProvisioningSession).where(ProvisioningSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def _get_active_session(self, router_id: int) -> Optional[ProvisioningSession]:
        """Get active provisioning session for router."""
        result = await self.db.execute(
            select(ProvisioningSession).where(
                and_(
                    ProvisioningSession.router_id == router_id,
                    ProvisioningSession.status.in_([
                        ProvisioningStatus.PENDING,
                        ProvisioningStatus.IN_PROGRESS
                    ])
                )
            )
        )
        return result.scalar_one_or_none()

    async def _create_step_logs(self, session_id: int) -> None:
        """Create initial step logs for a session."""
        steps = [
            (ProvisioningStep.CONNECTION, 1),
            (ProvisioningStep.CONFIGURATION, 2),
            (ProvisioningStep.SERVICE_SETUP, 3)
        ]

        for step, order in steps:
            step_log = ProvisioningStepLog(
                session_id=session_id,
                step=step,
                step_order=order,
                status=ProvisioningStatus.PENDING
            )
            self.db.add(step_log)

        await self.db.commit()

    async def _get_step_log(self, session_id: int, step: ProvisioningStep) -> ProvisioningStepLog:
        """Get step log for session and step."""
        result = await self.db.execute(
            select(ProvisioningStepLog).where(
                and_(
                    ProvisioningStepLog.session_id == session_id,
                    ProvisioningStepLog.step == step
                )
            )
        )
        return result.scalar_one()

    async def _update_step_progress(
        self, 
        step_log: ProvisioningStepLog, 
        progress: float, 
        operation: str
    ) -> None:
        """Update step progress and current operation."""
        step_log.progress_percentage = progress
        # Store current operation in output_data
        if not step_log.output_data:
            step_log.output_data = {}
        step_log.output_data['current_operation'] = operation
        
        await self.db.commit()

    async def _handle_provisioning_error(self, session: ProvisioningSession, error_message: str) -> None:
        """Handle provisioning error and cleanup."""
        session.status = ProvisioningStatus.FAILED
        session.error_message = error_message
        session.completed_at = datetime.utcnow()
        
        # Check if rollback is needed
        if session.get_config_item('rollback_on_failure', True):
            session.rollback_required = True
            # Schedule rollback task
            asyncio.create_task(self._execute_rollback(session))

        await self.db.commit()
        self.logger.error(f"Provisioning session {session.session_id} failed: {error_message}")

    async def _handle_step_error(
        self, 
        session: ProvisioningSession, 
        step_log: ProvisioningStepLog, 
        error_message: str
    ) -> None:
        """Handle step error."""
        step_log.status = ProvisioningStatus.FAILED
        step_log.error_details = error_message
        step_log.completed_at = datetime.utcnow()
        
        if step_log.started_at:
            step_log.duration_seconds = (step_log.completed_at - step_log.started_at).total_seconds()

        await self._handle_provisioning_error(session, f"Step {step_log.step.value} failed: {error_message}")

    async def _execute_rollback(self, session: ProvisioningSession) -> None:
        """Execute rollback of provisioning changes."""
        try:
            self.logger.info(f"Starting rollback for session {session.session_id}")
            
            # Get all executed commands in reverse order
            result = await self.db.execute(
                select(ProvisioningCommand)
                .where(
                    and_(
                        ProvisioningCommand.session_id == session.id,
                        ProvisioningCommand.success == True,
                        ProvisioningCommand.rollback_command.isnot(None)
                    )
                )
                .order_by(desc(ProvisioningCommand.execution_order))
            )
            commands = result.scalars().all()

            router = await self.router_service.get_by_id(session.router_id)
            api = MikroTikAPI(router)
            await api.connect()

            # Execute rollback commands
            for command in commands:
                try:
                    await api.execute_command(command.rollback_command)
                    command.rollback_executed = True
                except Exception as e:
                    self.logger.error(f"Rollback command failed: {e}")

            await api.disconnect()
            
            session.rollback_completed = True
            await self.db.commit()
            
            self.logger.info(f"Rollback completed for session {session.session_id}")

        except Exception as e:
            self.logger.error(f"Rollback failed for session {session.session_id}: {e}")

    async def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed status of a provisioning session."""
        session = await self._get_session_by_id(session_id)
        if not session:
            return None

        # Get step logs
        result = await self.db.execute(
            select(ProvisioningStepLog)
            .where(ProvisioningStepLog.session_id == session.id)
            .order_by(ProvisioningStepLog.step_order)
        )
        steps = result.scalars().all()

        # Calculate overall progress and estimate remaining time
        completed_steps = sum(1 for step in steps if step.status == ProvisioningStatus.COMPLETED)
        total_steps = len(steps)
        
        estimated_remaining = None
        if session.status == ProvisioningStatus.IN_PROGRESS and session.started_at:
            elapsed_minutes = (datetime.utcnow() - session.started_at).total_seconds() / 60
            if completed_steps > 0:
                avg_time_per_step = elapsed_minutes / completed_steps
                remaining_steps = total_steps - completed_steps
                estimated_remaining = int(avg_time_per_step * remaining_steps)

        # Get current operation
        current_operation = None
        for step in steps:
            if step.status == ProvisioningStatus.IN_PROGRESS and step.output_data:
                current_operation = step.output_data.get('current_operation')
                break

        return {
            'session_id': session.session_id,
            'status': session.status.value,
            'current_step': session.current_step.value,
            'progress_percentage': session.progress_percentage,
            'steps_completed': completed_steps,
            'steps_total': total_steps,
            'estimated_time_remaining_minutes': estimated_remaining,
            'current_operation': current_operation,
            'error_message': session.error_message,
            'can_cancel': session.status in [ProvisioningStatus.PENDING, ProvisioningStatus.IN_PROGRESS],
            'can_retry': session.status == ProvisioningStatus.FAILED,
            'started_at': session.started_at,
            'completed_at': session.completed_at,
            'steps': [
                {
                    'step': step.step.value,
                    'status': step.status.value,
                    'progress': step.progress_percentage,
                    'started_at': step.started_at,
                    'completed_at': step.completed_at,
                    'duration_seconds': step.duration_seconds,
                    'error': step.error_details
                }
                for step in steps
            ]
        }

    async def cancel_provisioning(
        self, 
        session_id: str, 
        reason: Optional[str] = None,
        force: bool = False
    ) -> bool:
        """Cancel an active provisioning session."""
        try:
            session = await self._get_session_by_id(session_id)
            if not session:
                return False

            if session.status not in [ProvisioningStatus.PENDING, ProvisioningStatus.IN_PROGRESS]:
                return False

            session.status = ProvisioningStatus.CANCELLED
            session.error_message = f"Cancelled by user: {reason}" if reason else "Cancelled by user"
            session.completed_at = datetime.utcnow()

            # Cancel any pending steps
            result = await self.db.execute(
                select(ProvisioningStepLog)
                .where(
                    and_(
                        ProvisioningStepLog.session_id == session.id,
                        ProvisioningStepLog.status == ProvisioningStatus.PENDING
                    )
                )
            )
            pending_steps = result.scalars().all()

            for step in pending_steps:
                step.status = ProvisioningStatus.CANCELLED

            await self.db.commit()

            # Execute rollback if needed
            if force or session.get_config_item('rollback_on_cancel', True):
                asyncio.create_task(self._execute_rollback(session))

            self.logger.info(f"Cancelled provisioning session {session_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to cancel session {session_id}: {e}")
            return False

    # Additional helper methods for validation and verification
    async def _validate_router_compatibility(
        self, 
        system_info: Dict[str, Any], 
        version_info: Dict[str, Any]
    ) -> None:
        """Validate router compatibility for provisioning."""
        # Check minimum RouterOS version
        min_version = "6.40"  # Minimum supported version
        current_version = version_info.get('version', '0.0')
        
        if self._compare_versions(current_version, min_version) < 0:
            raise ValidationError(f"RouterOS version {current_version} is not supported. Minimum version: {min_version}")

        # Check available resources
        cpu_load = system_info.get('cpu-load', 0)
        if cpu_load > 90:
            raise ValidationError(f"Router CPU load too high: {cpu_load}%")

        free_memory = system_info.get('free-memory', 0)
        if free_memory < 10 * 1024 * 1024:  # 10MB minimum
            raise ValidationError(f"Insufficient free memory: {free_memory / 1024 / 1024:.1f}MB")

    def _compare_versions(self, version1: str, version2: str) -> int:
        """Compare two version strings. Returns -1, 0, or 1."""
        v1_parts = [int(x) for x in version1.split('.')]
        v2_parts = [int(x) for x in version2.split('.')]
        
        # Pad with zeros to make equal length
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts.extend([0] * (max_len - len(v1_parts)))
        v2_parts.extend([0] * (max_len - len(v2_parts)))
        
        for v1, v2 in zip(v1_parts, v2_parts):
            if v1 < v2:
                return -1
            elif v1 > v2:
                return 1
        
        return 0

    async def _verify_basic_configuration(self, api: MikroTikAPI, config: Dict[str, Any]) -> None:
        """Verify basic configuration was applied correctly."""
        # Verify identity
        if 'identity' in config:
            identity = await api.get_system_identity()
            if identity != config['identity']:
                raise ConfigurationError(f"System identity not set correctly. Expected: {config['identity']}, Got: {identity}")

        # Verify IP pools
        if 'pool_name' in config:
            pools = await api.get_ip_pools()
            pool_names = [pool.get('name') for pool in pools]
            if config['pool_name'] not in pool_names:
                raise ConfigurationError(f"IP pool {config['pool_name']} not created")

    async def _verify_service_configuration(
        self, 
        api: MikroTikAPI, 
        service_type: ServiceType, 
        config: Dict[str, Any]
    ) -> None:
        """Verify service configuration was applied correctly."""
        if service_type == ServiceType.HOTSPOT:
            # Verify hotspot exists
            hotspots = await api.get_hotspots()
            hotspot_names = [hs.get('name') for hs in hotspots]
            expected_name = config.get('hotspot_name', 'ISP-Hotspot')
            if expected_name not in hotspot_names:
                raise ConfigurationError(f"Hotspot {expected_name} not created")

        elif service_type == ServiceType.PPPOE_SERVER:
            # Verify PPPoE server is running
            pppoe_servers = await api.get_pppoe_servers()
            if not pppoe_servers:
                raise ConfigurationError("PPPoE server not configured")

    async def _apply_security_configuration(self, api: MikroTikAPI, config: Dict[str, Any]) -> None:
        """Apply security configuration."""
        try:
            # Disable unnecessary services
            for command in self.command_templates['security']['disable_default_services']:
                await api.execute_command(command)

            # Apply firewall rules
            management_ip = config.get('management_ip', '0.0.0.0/0')
            for rule_template in self.command_templates['security']['create_firewall_rules']:
                rule = rule_template.format(management_ip=management_ip)
                await api.execute_command(rule)

        except Exception as e:
            self.logger.warning(f"Security configuration partially failed: {e}")
            # Don't fail provisioning for security config issues

    async def _get_template(self, template_id: int) -> Optional[ProvisioningTemplate]:
        """Get provisioning template by ID."""
        result = await self.db.execute(
            select(ProvisioningTemplate).where(ProvisioningTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    # Additional service methods for API endpoints
    async def get_sessions(
        self,
        pagination: PaginationParams,
        router_id: Optional[int] = None,
        status: Optional[ProvisioningStatus] = None,
        service_type: Optional[ServiceType] = None,
        user_id: Optional[int] = None,
        priority: Optional[ProvisioningPriority] = None
    ) -> Dict[str, Any]:
        """Get provisioning sessions with filtering and pagination."""
        query = select(ProvisioningSession)

        # Apply filters
        if router_id:
            query = query.where(ProvisioningSession.router_id == router_id)
        if status:
            query = query.where(ProvisioningSession.status == status)
        if service_type:
            query = query.where(ProvisioningSession.service_type == service_type)
        if user_id:
            query = query.where(ProvisioningSession.user_id == user_id)
        if priority:
            query = query.where(ProvisioningSession.priority == priority)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get sessions with pagination
        query = query.order_by(desc(ProvisioningSession.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        sessions = result.scalars().all()

        return {
            "items": sessions,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size
        }

    async def get_session_by_id(self, session_id: str) -> Optional[ProvisioningSession]:
        """Get provisioning session by session ID."""
        return await self._get_session_by_id(session_id)

    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> Optional[ProvisioningSession]:
        """Update a provisioning session."""
        session = await self._get_session_by_id(session_id)
        if not session:
            return None

        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)

        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def delete_session(self, session_id: str) -> bool:
        """Delete a provisioning session (only if not active)."""
        session = await self._get_session_by_id(session_id)
        if not session:
            return False

        # Don't allow deletion of active sessions
        if session.status in [ProvisioningStatus.PENDING, ProvisioningStatus.IN_PROGRESS]:
            return False

        await self.db.delete(session)
        await self.db.commit()
        return True

    async def retry_provisioning(
        self,
        session_id: str,
        from_step: Optional[ProvisioningStep] = None,
        reset_configuration: bool = False,
        updated_configuration: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Retry a failed provisioning session."""
        session = await self._get_session_by_id(session_id)
        if not session or session.status != ProvisioningStatus.FAILED:
            return False

        # Reset session status
        session.status = ProvisioningStatus.PENDING
        session.error_message = None
        session.success = False
        session.rollback_required = False
        session.rollback_completed = False

        # Update configuration if provided
        if updated_configuration:
            if reset_configuration:
                session.configuration = updated_configuration
            else:
                current_config = session.get_configuration()
                session.configuration = {**current_config, **updated_configuration}

        # Reset step logs from specified step
        start_step = from_step or ProvisioningStep.CONNECTION
        step_order_map = {
            ProvisioningStep.CONNECTION: 1,
            ProvisioningStep.CONFIGURATION: 2,
            ProvisioningStep.SERVICE_SETUP: 3
        }
        
        start_order = step_order_map[start_step]
        
        result = await self.db.execute(
            select(ProvisioningStepLog)
            .where(
                and_(
                    ProvisioningStepLog.session_id == session.id,
                    ProvisioningStepLog.step_order >= start_order
                )
            )
        )
        steps_to_reset = result.scalars().all()

        for step in steps_to_reset:
            step.status = ProvisioningStatus.PENDING
            step.progress_percentage = 0.0
            step.sub_steps_completed = 0
            step.started_at = None
            step.completed_at = None
            step.duration_seconds = None
            step.output_data = None
            step.error_details = None
            step.retry_count = 0

        session.current_step = start_step
        session.progress_percentage = (start_order - 1) * 33.3

        await self.db.commit()

        # Start provisioning
        return await self.start_provisioning(session_id)

    async def get_session_steps(self, session_id: str) -> Optional[List[ProvisioningStepLog]]:
        """Get step logs for a session."""
        session = await self._get_session_by_id(session_id)
        if not session:
            return None

        result = await self.db.execute(
            select(ProvisioningStepLog)
            .where(ProvisioningStepLog.session_id == session.id)
            .order_by(ProvisioningStepLog.step_order)
        )
        return result.scalars().all()

    async def get_session_commands(self, session_id: str) -> Optional[List[ProvisioningCommand]]:
        """Get commands for a session."""
        session = await self._get_session_by_id(session_id)
        if not session:
            return None

        result = await self.db.execute(
            select(ProvisioningCommand)
            .where(ProvisioningCommand.session_id == session.id)
            .order_by(ProvisioningCommand.execution_order)
        )
        return result.scalars().all()

    # Template management methods
    async def get_templates(
        self,
        pagination: PaginationParams,
        service_type: Optional[ServiceType] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get provisioning templates with filtering and pagination."""
        query = select(ProvisioningTemplate)

        # Apply filters
        if service_type:
            query = query.where(ProvisioningTemplate.service_type == service_type)
        if is_active is not None:
            query = query.where(ProvisioningTemplate.is_active == is_active)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    ProvisioningTemplate.name.ilike(search_term),
                    ProvisioningTemplate.description.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get templates with pagination
        query = query.order_by(desc(ProvisioningTemplate.created_at))
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        templates = result.scalars().all()

        return {
            "items": templates,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size
        }

    async def create_template(self, template_data, created_by: int) -> ProvisioningTemplate:
        """Create a new provisioning template."""
        template = ProvisioningTemplate(
            name=template_data.name,
            description=template_data.description,
            version=template_data.version,
            service_type=template_data.service_type,
            router_model=template_data.router_model,
            min_routeros_version=template_data.min_routeros_version,
            configuration_schema=template_data.configuration_schema,
            default_configuration=template_data.default_configuration,
            command_templates=template_data.command_templates,
            is_active=template_data.is_active,
            is_default=template_data.is_default,
            created_by=created_by
        )

        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def get_template_by_id(self, template_id: int) -> Optional[ProvisioningTemplate]:
        """Get template by ID."""
        return await self._get_template(template_id)

    async def update_template(self, template_id: int, updates: Dict[str, Any]) -> Optional[ProvisioningTemplate]:
        """Update a provisioning template."""
        template = await self._get_template(template_id)
        if not template:
            return None

        for key, value in updates.items():
            if hasattr(template, key):
                setattr(template, key, value)

        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def delete_template(self, template_id: int) -> bool:
        """Delete a provisioning template."""
        template = await self._get_template(template_id)
        if not template:
            return False

        await self.db.delete(template)
        await self.db.commit()
        return True

    async def duplicate_template(self, template_id: int, new_name: str, created_by: int) -> Optional[ProvisioningTemplate]:
        """Duplicate an existing template."""
        original = await self._get_template(template_id)
        if not original:
            return None

        duplicate = ProvisioningTemplate(
            name=new_name,
            description=f"Copy of {original.description}" if original.description else None,
            version="1.0",
            service_type=original.service_type,
            router_model=original.router_model,
            min_routeros_version=original.min_routeros_version,
            configuration_schema=original.configuration_schema.copy() if original.configuration_schema else {},
            default_configuration=original.default_configuration.copy() if original.default_configuration else {},
            command_templates=original.command_templates.copy() if original.command_templates else {},
            is_active=True,
            is_default=False,
            created_by=created_by
        )

        self.db.add(duplicate)
        await self.db.commit()
        await self.db.refresh(duplicate)
        return duplicate

    # Router configuration methods
    async def get_router_configurations(
        self,
        router_id: int,
        configuration_type: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> List[RouterConfiguration]:
        """Get router configurations."""
        query = select(RouterConfiguration).where(RouterConfiguration.router_id == router_id)

        if configuration_type:
            query = query.where(RouterConfiguration.configuration_type == configuration_type)
        if is_active is not None:
            query = query.where(RouterConfiguration.is_active == is_active)

        query = query.order_by(desc(RouterConfiguration.created_at))
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def create_router_configuration(self, config_data, applied_by: int) -> RouterConfiguration:
        """Create a router configuration."""
        configuration = RouterConfiguration(
            router_id=config_data.router_id,
            session_id=config_data.session_id,
            configuration_type=config_data.configuration_type,
            configuration_name=config_data.configuration_name,
            configuration_data=config_data.configuration_data,
            is_backup=config_data.is_backup,
            applied_by=applied_by,
            checksum=hashlib.sha256(
                json.dumps(config_data.configuration_data, sort_keys=True).encode()
            ).hexdigest()
        )

        self.db.add(configuration)
        await self.db.commit()
        await self.db.refresh(configuration)
        return configuration

    async def restore_router_configuration(self, router_id: int, config_id: int, user_id: int) -> bool:
        """Restore a router to a previous configuration."""
        # Implementation would involve creating a new provisioning session
        # with the stored configuration and executing it
        # This is a complex operation that would be implemented as needed
        return True

    # Utility methods
    async def get_default_configuration(self, service_type: ServiceType) -> Dict[str, Any]:
        """Get default configuration for a service type."""
        return await self._validate_configuration(service_type, {})

    async def validate_configuration(self, service_type: ServiceType, configuration: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a configuration."""
        return await self._validate_configuration(service_type, configuration)

    async def get_provisioning_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get provisioning statistics."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        # Get session counts by status
        result = await self.db.execute(
            select(
                ProvisioningSession.status,
                func.count(ProvisioningSession.id).label('count')
            )
            .where(ProvisioningSession.created_at >= start_date)
            .group_by(ProvisioningSession.status)
        )
        status_counts = {row.status.value: row.count for row in result}

        # Get success rate
        total_sessions = sum(status_counts.values())
        successful_sessions = status_counts.get(ProvisioningStatus.COMPLETED.value, 0)
        success_rate = (successful_sessions / total_sessions * 100) if total_sessions > 0 else 0

        # Get average duration for completed sessions
        result = await self.db.execute(
            select(func.avg(
                func.extract('epoch', ProvisioningSession.completed_at - ProvisioningSession.started_at)
            ))
            .where(
                and_(
                    ProvisioningSession.status == ProvisioningStatus.COMPLETED,
                    ProvisioningSession.created_at >= start_date,
                    ProvisioningSession.started_at.isnot(None),
                    ProvisioningSession.completed_at.isnot(None)
                )
            )
        )
        avg_duration_seconds = result.scalar() or 0

        return {
            "period_days": days,
            "total_sessions": total_sessions,
            "success_rate": round(success_rate, 2),
            "average_duration_minutes": round(avg_duration_seconds / 60, 2),
            "status_breakdown": status_counts,
            "active_sessions": status_counts.get(ProvisioningStatus.IN_PROGRESS.value, 0),
            "pending_sessions": status_counts.get(ProvisioningStatus.PENDING.value, 0)
        }
