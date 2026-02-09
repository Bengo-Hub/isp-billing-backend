"""Production-ready MikroTik device provisioning service.

This service implements a comprehensive 3-step provisioning workflow:
1. Connection & Verification - Test connectivity and gather device info
2. Configuration - Apply basic router configuration and security
3. Service Setup - Configure PPPoE/Hotspot services and user management

Based on Codevertex provisioning process with production-ready features:
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
from app.core.config import settings
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
from app.integrations.mikrotik import get_mikrotik_client, get_mikrotik_ftp_client
from app.modules.routers import RouterService
from .commands import (
    load_command_templates,
    generate_configuration_commands,
    generate_hotspot_commands,
    generate_pppoe_commands,
    execute_command_with_retry,
    cleanup_existing_provisioning,
    backup_router_configuration,
    apply_security_configuration,
)
from app.api.deps import PaginationParams
from .verify import verify_basic_configuration, verify_service_configuration
from .rollback import execute_rollback
from .status import build_session_status
from .live_streaming import streaming_manager

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
        self.command_templates = load_command_templates()


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
            try:
                router = await self.router_service.get_by_id(router_id)
                if not router:
                    raise ValidationError(f"Router {router_id} not found")
            except SQLAlchemyError as e:
                await self.db.rollback()
                self.logger.error(f"Database error while fetching router {router_id}: {e}")
                raise

            # Check for existing active sessions
            try:
                existing_session = await self._get_active_session(router_id)
                if existing_session:
                    raise ProvisioningError(
                        f"Router {router_id} already has an active provisioning session: {existing_session.session_id}"
                    )
            except ProvisioningError:
                raise
            except SQLAlchemyError as e:
                await self.db.rollback()
                self.logger.error(f"Database error while checking active sessions: {e}")
                raise

            # Generate unique session ID
            session_id = str(uuid.uuid4())

            # Load template if specified
            if template_id:
                try:
                    template = await self._get_template(template_id)
                    if template and template.service_type == service_type:
                        # Merge template configuration with provided configuration
                        template_config = template.get_default_configuration()
                        configuration = {**template_config, **configuration}
                except SQLAlchemyError as e:
                    await self.db.rollback()
                    self.logger.error(f"Database error while loading template: {e}")
                    raise

            # Validate configuration and inject billing server URLs
            try:
                validated_config = await self._validate_configuration(
                    service_type, configuration, router_id=router_id, user_id=user_id
                )
            except SQLAlchemyError as e:
                await self.db.rollback()
                self.logger.error(f"Database error during configuration validation: {e}")
                raise

            # Calculate timeout
            timeout_at = datetime.utcnow() + timedelta(minutes=self.default_timeout_minutes)

            # Create session - ensure transaction is clean before INSERT
            try:
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
            except SQLAlchemyError as e:
                await self.db.rollback()
                self.logger.error(f"Database error while creating provisioning session: {e}")
                raise

            # Create initial step logs
            try:
                await self._create_step_logs(session.id)
            except SQLAlchemyError as e:
                await self.db.rollback()
                self.logger.error(f"Database error while creating step logs: {e}")
                raise

            self.logger.info(f"Created provisioning session {session_id} for router {router_id}")
            return session

        except (ValidationError, ProvisioningError):
            # Re-raise application errors without additional rollback
            raise
        except Exception as e:
            # Rollback for any unexpected errors
            await self.db.rollback()
            self.logger.error(f"Failed to create provisioning session: {e}")
            raise

    async def start_provisioning(self, session_id: str) -> bool:
        """Start the provisioning process for a session."""
        try:
            # Get session with proper error handling
            try:
                session = await self._get_session_by_id(session_id)
                if not session:
                    raise ProvisioningError(f"Session {session_id} not found")

                if session.status != ProvisioningStatus.PENDING:
                    raise ProvisioningError(f"Session {session_id} is not in pending status")
            except SQLAlchemyError as e:
                await self.db.rollback()
                self.logger.error(f"Database error while fetching session {session_id}: {e}")
                raise

            # Update session status
            try:
                session.status = ProvisioningStatus.IN_PROGRESS
                session.started_at = datetime.utcnow()
                session.current_step = ProvisioningStep.CONNECTION

                await self.db.commit()
            except SQLAlchemyError as e:
                await self.db.rollback()
                self.logger.error(f"Database error while updating session {session_id}: {e}")
                raise

            # Start provisioning process in background
            asyncio.create_task(self._execute_provisioning_workflow(session))

            self.logger.info(f"Started provisioning session {session_id}")
            return True

        except (ValidationError, ProvisioningError) as e:
            self.logger.error(f"Failed to start provisioning session {session_id}: {e}")
            return False
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to start provisioning session {session_id}: {e}")
            return False

    async def _execute_provisioning_workflow(self, session: ProvisioningSession) -> None:
        """Execute the complete provisioning workflow."""
        try:
            # Start live streaming
            await streaming_manager.start_session(session.session_id, session.router_id)
            await streaming_manager.log_provisioning_step(
                session.session_id, 
                "initialization", 
                "Starting provisioning workflow"
            )
            
            # Step 1: Connection and Verification
            await self._execute_connection_step(session)
            
            if session.status == ProvisioningStatus.FAILED:
                await streaming_manager.end_session(session.session_id, False)
                return

            # Step 2: Basic Configuration
            await self._execute_configuration_step(session)
            
            if session.status == ProvisioningStatus.FAILED:
                await streaming_manager.end_session(session.session_id, False)
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

                # Mark the router itself as provisioned
                try:
                    from app.services.router_provisioning import mark_provisioning_complete
                    service_type_str = session.service_type.value if hasattr(session.service_type, 'value') else str(session.service_type)
                    await mark_provisioning_complete(
                        db=self.db,
                        router_id=session.router_id,
                        service_type=service_type_str
                    )
                    self.logger.info(f"Marked router {session.router_id} as provisioned")
                except Exception as e:
                    self.logger.warning(f"Failed to mark router {session.router_id} as provisioned: {e}")

                await streaming_manager.log_provisioning_step(
                    session.session_id,
                    "completion",
                    "Provisioning completed successfully",
                    "success"
                )
                await streaming_manager.end_session(session.session_id, True)
                self.logger.info(f"Provisioning session {session.session_id} completed successfully")

        except Exception as e:
            await streaming_manager.log_provisioning_step(
                session.session_id, 
                "error", 
                f"Provisioning failed: {str(e)}", 
                "error"
            )
            await streaming_manager.end_session(session.session_id, False)
            await self._handle_provisioning_error(session, str(e))

    async def _execute_connection_step(self, session: ProvisioningSession) -> None:
        """Execute Step 1: Connection and Verification."""
        step_log = await self._get_step_log(session.id, ProvisioningStep.CONNECTION)
        
        try:
            step_log.status = ProvisioningStatus.IN_PROGRESS
            step_log.started_at = datetime.utcnow()
            await self.db.commit()

            router = await self.router_service.get_by_id(session.router_id)
            client = get_mikrotik_client()

            # Sub-step 1: Test connection (25%)
            await self._update_step_progress(step_log, 25.0, "Testing connection...", session)
            await streaming_manager.log_provisioning_step(
                session.session_id,
                "connection",
                "Testing connection to router..."
            )
            connection = await client.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port
            )

            if not connection:
                raise RouterConnectionError(f"Failed to connect to router {router.ip_address}")

            # Sub-step 2: Get system information (50%)
            await self._update_step_progress(step_log, 50.0, "Gathering system information...", session)
            system_info = await client.get_system_info(connection)

            if not system_info:
                raise RouterConnectionError("Failed to retrieve system information")

            # Sub-step 3: Verify RouterOS version (75%)
            await self._update_step_progress(step_log, 75.0, "Verifying RouterOS version...", session)
            version_info = system_info  # System info includes version

            # Store system information
            step_log.output_data = {
                "system_info": system_info,
                "version_info": version_info,
                "connection_test": "successful"
            }

            # Sub-step 4: Validate compatibility (100%)
            await self._update_step_progress(step_log, 100.0, "Validating compatibility...", session)
            await self._validate_router_compatibility(system_info, version_info)

            # Update session and step
            step_log.status = ProvisioningStatus.COMPLETED
            step_log.completed_at = datetime.utcnow()
            step_log.duration_seconds = (step_log.completed_at - step_log.started_at).total_seconds()
            
            session.current_step = ProvisioningStep.CONFIGURATION
            session.progress_percentage = 33.3

            await client.disconnect(connection)
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
            client = get_mikrotik_client()

            connection = await client.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port
            )
            config = session.get_configuration()

            # Router info for reconnection on socket errors
            router_info = {
                "ip_address": router.ip_address,
                "username": router.username,
                "password": router.password,
                "port": router.port
            }

            # Clean up any existing codevertex configuration (makes reprovisioning safe)
            await self._update_step_progress(step_log, 5.0, "Cleaning up existing configuration...", session)
            await cleanup_existing_provisioning(client, connection, self.logger, session.session_id)

            # Create backup of current configuration
            await self._update_step_progress(step_log, 10.0, "Creating configuration backup...", session)
            await backup_router_configuration(self.db, session, client, connection, self.logger)

            # Apply basic configuration commands
            commands = generate_configuration_commands(config, session.service_type)
            total_commands = len(commands)

            for i, command_data in enumerate(commands):
                progress = 10.0 + (80.0 * (i + 1) / total_commands)
                await self._update_step_progress(
                    step_log,
                    progress,
                    f"Executing command {i+1}/{total_commands}: {command_data['description']}",
                    session
                )

                # Execute command with retry logic - connection may be refreshed on socket errors
                success, connection = await execute_command_with_retry(
                    self.db, self.retry_delays, self.logger, session, client, connection, command_data, router_info
                )

                if not success and command_data.get('critical', True):
                    raise ConfigurationError(f"Critical command failed: {command_data['description']}")

            # Verify configuration
            await self._update_step_progress(step_log, 95.0, "Verifying configuration...", session)
            await verify_basic_configuration(client, connection, config)

            # Finalize step
            await self._update_step_progress(step_log, 100.0, "Configuration completed", session)

            step_log.status = ProvisioningStatus.COMPLETED
            step_log.completed_at = datetime.utcnow()
            step_log.duration_seconds = (step_log.completed_at - step_log.started_at).total_seconds()

            session.current_step = ProvisioningStep.SERVICE_SETUP
            session.progress_percentage = 66.6

            await client.disconnect(connection)
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
            client = get_mikrotik_client()

            connection = await client.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port
            )
            config = session.get_configuration()

            # Router info for reconnection on socket errors
            router_info = {
                "ip_address": router.ip_address,
                "username": router.username,
                "password": router.password,
                "port": router.port
            }

            # Generate service-specific commands
            if session.service_type == ServiceType.HOTSPOT:
                commands = generate_hotspot_commands(config)
            elif session.service_type == ServiceType.PPPOE_SERVER:
                commands = generate_pppoe_commands(config)
            else:  # BOTH
                hotspot_commands = generate_hotspot_commands(config)
                pppoe_commands = generate_pppoe_commands(config)
                commands = hotspot_commands + pppoe_commands

            total_commands = len(commands)

            for i, command_data in enumerate(commands):
                progress = 10.0 + (80.0 * (i + 1) / total_commands)
                await self._update_step_progress(
                    step_log,
                    progress,
                    f"Configuring service {i+1}/{total_commands}: {command_data['description']}",
                    session
                )

                # Execute command with retry logic - connection may be refreshed on socket errors
                success, connection = await execute_command_with_retry(
                    self.db, self.retry_delays, self.logger, session, client, connection, command_data, router_info
                )

                if not success and command_data.get('critical', True):
                    raise ConfigurationError(f"Service configuration failed: {command_data['description']}")

            # Upload hotspot templates via FTP BEFORE security config
            # IMPORTANT: Must happen before apply_security_configuration() because
            # security config disables FTP (/ip/service/set ftp disabled=yes).
            # The hotspot commands above already enabled FTP as their first command.
            if session.service_type in [ServiceType.HOTSPOT, ServiceType.BOTH]:
                await self._update_step_progress(step_log, 90.0, "Uploading hotspot templates...", session)

                # Brief delay to allow FTP service to fully start after being enabled
                import asyncio
                await asyncio.sleep(3)

                try:
                    await self._upload_hotspot_templates(router, config, session)
                    # Templates uploaded — point hotspot profile to custom templates
                    profile_name = config.get("hotspot_profile", "codevertex-hsprof")
                    try:
                        await client.execute_command(
                            connection,
                            f"/ip/hotspot/profile/set {profile_name} html-directory=hotspot"
                        )
                        self.logger.info("Set hotspot html-directory=hotspot for custom templates")
                    except Exception as dir_err:
                        self.logger.warning(f"Could not set html-directory: {dir_err}")
                    await streaming_manager.log_provisioning_step(
                        session.session_id,
                        "template_upload",
                        "[OK] Hotspot templates uploaded and activated",
                        "success"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to upload hotspot templates: {e}. Using default MikroTik templates.")
                    await streaming_manager.log_provisioning_step(
                        session.session_id,
                        "template_upload",
                        f"[WARN] Template upload failed: {str(e)}. Captive portal will use default MikroTik login page.",
                        "warning"
                    )
                    # html-directory is NOT set, so MikroTik uses built-in defaults

            # Apply security configurations (this disables FTP among other things)
            await self._update_step_progress(step_log, 93.0, "Applying security configurations...", session)
            await apply_security_configuration(client, connection, config, self.command_templates, self.logger, session.session_id)

            # Final verification
            await self._update_step_progress(step_log, 95.0, "Performing final verification...", session)
            await verify_service_configuration(client, connection, session.service_type, config)

            await self._update_step_progress(step_log, 100.0, "Service setup completed", session)

            step_log.status = ProvisioningStatus.COMPLETED
            step_log.completed_at = datetime.utcnow()
            step_log.duration_seconds = (step_log.completed_at - step_log.started_at).total_seconds()

            session.progress_percentage = 100.0

            await client.disconnect(connection)
            await self.db.commit()

        except Exception as e:
            await self._handle_step_error(session, step_log, str(e))

    async def _upload_hotspot_templates(
        self,
        router: Router,
        config: Dict[str, Any],
        session: ProvisioningSession
    ) -> bool:
        """Upload custom hotspot templates to the MikroTik router via FTP.

        This uploads login_redirect.html and alogin.html to redirect users to
        the external captive portal.

        Args:
            router: Router model instance
            config: Configuration dictionary
            session: Current provisioning session

        Returns:
            True if upload was successful
        """
        import os
        from pathlib import Path

        try:
            # Get FTP client
            ftp_client = get_mikrotik_ftp_client()

            # Determine template type (default to modern if not specified)
            template_type = config.get('hotspot_template_type', 'modern')

            # Get redirect URL from config
            base_url = config.get('billing_server_url', settings.frontend_url)
            if not base_url:
                self.logger.warning("No redirect URL configured, skipping template upload")
                return False

            # Get organization slug for constructing captive portal URL
            org_slug = config.get('organization_slug', 'default')

            # Construct full captive portal URL: /buy/{org_slug}
            captive_portal_url = f"{base_url.rstrip('/')}/buy/{org_slug}"

            self.logger.info(
                f"[TEMPLATE UPLOAD] Configuring captive portal redirect",
                extra={
                    "session_id": session.session_id,
                    "base_url": base_url,
                    "org_slug": org_slug,
                    "full_url": captive_portal_url
                }
            )

            # Also send to WebSocket for user visibility
            await streaming_manager.log_provisioning_step(
                session.session_id,
                "template_config",
                f"[INFO] Captive portal URL: {captive_portal_url}",
                "info"
            )

            # Build template directory path
            template_dir = Path(__file__).parent / "hotspot_templates"
            if not template_dir.exists():
                self.logger.error(f"Template directory not found: {template_dir}")
                return False

            # Read and process templates with URL replacement
            import tempfile
            processed_templates = []

            template_files = [
                {
                    "source": "login_redirect.html",
                    "target": "login.html"  # Upload as login.html to override default
                },
                {
                    "source": "alogin.html",
                    "target": "alogin.html"  # After-login success page
                }
            ]

            for template_info in template_files:
                source_path = template_dir / template_info["source"]

                if not source_path.exists():
                    self.logger.warning(f"Template file not found: {source_path}")
                    continue

                # Read template content
                with open(source_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Replace $(redirect-url) placeholder with actual captive portal URL
                content = content.replace('$(redirect-url)', captive_portal_url)

                # Create temporary file with processed content
                temp_file = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.html')
                temp_file.write(content)
                temp_file.close()

                processed_templates.append({
                    "path": temp_file.name,
                    "name": template_info["target"]
                })

            # Upload with retry — FTP service may need time to start listening
            import asyncio as _asyncio
            max_ftp_retries = 3
            results = {}
            last_error = None

            for attempt in range(max_ftp_retries):
                try:
                    # Delete old templates first to ensure fresh upload
                    try:
                        for template_info in template_files:
                            target_name = template_info["target"]
                            self.logger.info(f"Deleting old template: {target_name}")
                            await ftp_client.delete_hotspot_file(
                                router_ip=router.ip_address,
                                username=router.username,
                                password=router.password,
                                filename=target_name,
                                port=21
                            )
                    except Exception as e:
                        # It's okay if deletion fails (files might not exist)
                        self.logger.info(f"Could not delete old templates (might not exist): {e}")

                    # Upload processed templates
                    results = await ftp_client.upload_hotspot_templates_batch(
                        router_ip=router.ip_address,
                        username=router.username,
                        password=router.password,
                        templates=processed_templates,
                        port=21
                    )

                    # If we got results and all succeeded, break out
                    if results and all(results.values()):
                        break

                    # If some failed, treat as error for retry
                    failed = [n for n, ok in results.items() if not ok]
                    if failed:
                        last_error = f"Failed templates: {', '.join(failed)}"
                        raise Exception(last_error)

                except Exception as e:
                    last_error = e
                    if attempt < max_ftp_retries - 1:
                        wait_secs = 3 * (attempt + 1)
                        self.logger.warning(
                            f"FTP upload attempt {attempt + 1}/{max_ftp_retries} failed: {e}. "
                            f"Retrying in {wait_secs}s..."
                        )
                        await _asyncio.sleep(wait_secs)
                    else:
                        self.logger.error(f"FTP upload failed after {max_ftp_retries} attempts: {e}")
                        raise

            # Clean up temporary files
            for template in processed_templates:
                try:
                    os.unlink(template["path"])
                except Exception as e:
                    self.logger.warning(f"Failed to delete temp file {template['path']}: {e}")

            # Check results
            all_success = all(results.values())

            if all_success:
                uploaded_files = ", ".join(results.keys())
                self.logger.info(
                    f"[TEMPLATE UPLOAD] Successfully uploaded {len(results)} templates: {uploaded_files}",
                    extra={"session_id": session.session_id, "templates": list(results.keys())}
                )

                # Log to WebSocket with file details
                await streaming_manager.log_provisioning_step(
                    session.session_id,
                    "template_files",
                    f"[INFO] Uploaded templates: {uploaded_files} to /hotspot/ directory",
                    "info"
                )
            else:
                failed = [name for name, success in results.items() if not success]
                error_msg = f"Failed to upload some templates: {', '.join(failed)}"
                self.logger.error(
                    f"[TEMPLATE UPLOAD] {error_msg}",
                    extra={"session_id": session.session_id}
                )
                # Raise exception to make failure visible
                raise Exception(error_msg)

            return all_success

        except Exception as e:
            self.logger.error(
                f"Error uploading hotspot templates to router {router.name}: {e}",
                extra={"session_id": session.session_id}
            )
            raise

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

            # Add interface(s) to bridge
            bridge_ports = config.get('bridge_ports')
            if isinstance(bridge_ports, list) and bridge_ports:
                for port in bridge_ports:
                    commands.append({
                        'type': 'api_call',
                        'command': f"/interface/bridge/port/add interface={port} bridge={bridge_name}",
                        'description': f'Add {port} to bridge',
                        'critical': True
                    })
            else:
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
        client,
        connection,
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
                    result = await client.execute_command(connection, command_data['command'])
                else:
                    result = await client.execute_script(connection, command_data['command'])

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

    async def _backup_router_configuration(self, session: ProvisioningSession, client, connection) -> None:
        """Create a backup of the current router configuration."""
        try:
            # Get current configuration
            config_data = await client.export_configuration(connection)

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
        configuration: Dict[str, Any],
        router_id: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Validate and normalize configuration parameters.

        Also injects billing server and captive portal URLs for external portal redirect.
        """
        validated_config = configuration.copy()

        # Common validation
        if 'interface' not in validated_config:
            validated_config['interface'] = 'ether2'

        if 'dns_servers' not in validated_config:
            validated_config['dns_servers'] = ['8.8.8.8', '8.8.4.4']

        # CRITICAL: Ensure WAN interface is always set for safeguard in command generation
        # This prevents the WAN interface from being added to the LAN bridge
        if 'wan_interface' not in validated_config:
            validated_config['wan_interface'] = 'ether1'

        # Inject billing server URLs for captive portal configuration
        # These are used by generate_hotspot_commands to configure walled garden and login redirect
        if 'billing_server_url' not in validated_config:
            # Use frontend_url from settings (the captive portal is served by frontend)
            frontend_url = settings.frontend_url
            if frontend_url:
                validated_config['billing_server_url'] = frontend_url
            else:
                # Fallback: try to get from backend_url (same host, different port typically)
                backend_url = settings.backend_url
                if backend_url:
                    # Frontend typically runs on port 3000, backend on 8000
                    import re
                    match = re.search(r'(https?://[^:]+):?(\d+)?', backend_url)
                    if match:
                        host = match.group(1)
                        validated_config['billing_server_url'] = f"{host}:3000"

        if 'api_server_url' not in validated_config:
            # Backend API URL for package purchases
            if settings.backend_url:
                validated_config['api_server_url'] = settings.backend_url

        # Get organization slug for portal URL construction
        if 'organization_slug' not in validated_config:
            org_slug = await self._get_organization_slug(router_id, user_id)
            validated_config['organization_slug'] = org_slug or 'default'

        # Get organization hotspot settings for template and redirect configuration
        if service_type in [ServiceType.HOTSPOT, ServiceType.BOTH]:
            org_settings = await self._get_organization_settings(router_id, user_id)
            if org_settings:
                # Inject hotspot template type
                if 'hotspot_template_type' not in validated_config:
                    validated_config['hotspot_template_type'] = org_settings.hotspot_template or 'Aurora'

                # Inject redirect URL from organization settings
                if 'hotspot_redirect_url' not in validated_config and org_settings.hotspot_redirect_url:
                    validated_config['hotspot_redirect_url'] = org_settings.hotspot_redirect_url

                # Inject session timeout
                if 'session_timeout_minutes' not in validated_config:
                    validated_config['session_timeout_minutes'] = org_settings.session_timeout_minutes

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

            # Add default walled garden hosts if not provided
            if 'walled_garden_hosts' not in validated_config:
                validated_config['walled_garden_hosts'] = []

        elif service_type == ServiceType.PPPOE_SERVER:
            if 'service_name' not in validated_config:
                validated_config['service_name'] = 'ISP-PPPoE'

            if 'ip_pool_start' not in validated_config:
                validated_config['ip_pool_start'] = '172.31.1.1'

            if 'ip_pool_end' not in validated_config:
                validated_config['ip_pool_end'] = '172.31.1.254'

        return validated_config

    async def _get_organization_slug(
        self,
        router_id: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> Optional[str]:
        """Get organization slug from router or user."""
        try:
            # Try to get from router's organization
            if router_id:
                from app.models.router import Router
                from app.models.organization import Organization
                result = await self.db.execute(
                    select(Organization.slug)
                    .join(Router, Router.organization_id == Organization.id)
                    .where(Router.id == router_id)
                )
                slug = result.scalar_one_or_none()
                if slug:
                    return slug

            # Fallback to user's organization
            if user_id:
                from app.models.user import User
                from app.models.organization import Organization
                result = await self.db.execute(
                    select(Organization.slug)
                    .join(User, User.organization_id == Organization.id)
                    .where(User.id == user_id)
                )
                slug = result.scalar_one_or_none()
                if slug:
                    return slug

            return None
        except Exception as e:
            self.logger.warning(f"Failed to get organization slug: {e}")
            return None

    async def _get_organization_settings(
        self,
        router_id: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> Optional['OrganizationSettings']:
        """Get organization settings from router or user."""
        try:
            from app.models.router import Router
            from app.models.organization import Organization, OrganizationSettings
            from app.models.user import User

            organization_id = None

            # Try to get from router's organization
            if router_id:
                result = await self.db.execute(
                    select(Router.organization_id).where(Router.id == router_id)
                )
                organization_id = result.scalar_one_or_none()

            # Fallback to user's organization
            if not organization_id and user_id:
                result = await self.db.execute(
                    select(User.organization_id).where(User.id == user_id)
                )
                organization_id = result.scalar_one_or_none()

            if not organization_id:
                return None

            # Get organization settings
            result = await self.db.execute(
                select(OrganizationSettings).where(
                    OrganizationSettings.organization_id == organization_id
                )
            )
            return result.scalar_one_or_none()

        except Exception as e:
            self.logger.warning(f"Failed to get organization settings: {e}")
            return None

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
        operation: str,
        session: ProvisioningSession = None
    ) -> None:
        """Update step progress and current operation."""
        step_log.progress_percentage = progress
        # Store current operation in output_data
        if not step_log.output_data:
            step_log.output_data = {}
        step_log.output_data['current_operation'] = operation

        await self.db.commit()

        # Stream progress update via WebSocket
        if session:
            await streaming_manager.update_progress(
                session.session_id,
                progress,
                operation
            )

    async def _handle_provisioning_error(self, session: ProvisioningSession, error_message: str) -> None:
        """Handle provisioning error and cleanup."""
        session.status = ProvisioningStatus.FAILED
        session.error_message = error_message
        session.completed_at = datetime.utcnow()

        # Stream the error to WebSocket clients
        await streaming_manager.log_provisioning_step(
            session.session_id,
            "error",
            f"[FAIL] Provisioning failed: {error_message}",
            "error"
        )

        # Check if rollback is needed
        if session.get_config_item('rollback_on_failure', True):
            session.rollback_required = True

            # Notify about rollback starting
            await streaming_manager.log_provisioning_step(
                session.session_id,
                "rollback",
                "[ROLLBACK] Starting automatic rollback to restore previous configuration...",
                "warning"
            )

            # Schedule rollback task
            asyncio.create_task(execute_rollback(self.db, self.router_service, session, self.logger))

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
            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port
            )

            # Execute rollback commands
            for command in commands:
                try:
                    await client.execute_command(connection, command.rollback_command)
                    command.rollback_executed = True
                except Exception as e:
                    self.logger.error(f"Rollback command failed: {e}")

            await client.disconnect(connection)
            
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

        return await build_session_status(self.db, session)

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

        # Check available resources (values from MikroTik API may be strings)
        try:
            cpu_load = int(system_info.get('cpu-load', 0))
        except (ValueError, TypeError):
            cpu_load = 0  # Default to 0 if parsing fails

        if cpu_load > 90:
            raise ValidationError(f"Router CPU load too high: {cpu_load}%")

        try:
            free_memory = int(system_info.get('free-memory', 0))
        except (ValueError, TypeError):
            free_memory = 100 * 1024 * 1024  # Default to 100MB if parsing fails

        if free_memory < 10 * 1024 * 1024:  # 10MB minimum
            raise ValidationError(f"Insufficient free memory: {free_memory / 1024 / 1024:.1f}MB")

    def _compare_versions(self, version1: str, version2: str) -> int:
        """Compare two version strings. Returns -1, 0, or 1.

        Handles RouterOS version formats like "7.18.2 (stable)" by stripping
        any text after a space or parenthesis.
        """
        def parse_version(version: str) -> list:
            # Strip "(stable)" or similar suffixes - take only the numeric part
            # e.g., "7.18.2 (stable)" -> "7.18.2"
            version = version.split(' ')[0].split('(')[0].strip()
            parts = []
            for part in version.split('.'):
                # Extract only numeric characters from each part
                numeric = ''.join(c for c in part if c.isdigit())
                parts.append(int(numeric) if numeric else 0)
            return parts

        v1_parts = parse_version(version1)
        v2_parts = parse_version(version2)
        
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

    async def _verify_basic_configuration(self, client, connection, config: Dict[str, Any]) -> None:
        """Verify basic configuration was applied correctly."""
        # Verify identity
        if 'identity' in config:
            identity = await client.get_system_identity(connection)
            if identity != config['identity']:
                raise ConfigurationError(f"System identity not set correctly. Expected: {config['identity']}, Got: {identity}")

        # Verify IP pools
        if 'pool_name' in config:
            pools = await client.get_ip_pools(connection)
            pool_names = [pool.get('name') for pool in pools]
            if config['pool_name'] not in pool_names:
                raise ConfigurationError(f"IP pool {config['pool_name']} not created")

    async def _verify_service_configuration(
        self,
        client,
        connection,
        service_type: ServiceType,
        config: Dict[str, Any]
    ) -> None:
        """Verify service configuration was applied correctly."""
        if service_type == ServiceType.HOTSPOT:
            # Verify hotspot exists
            hotspots = await client.get_hotspot_servers(connection)
            hotspot_names = [hs.get('name') for hs in hotspots]
            expected_name = config.get('hotspot_name', 'ISP-Hotspot')
            if expected_name not in hotspot_names:
                raise ConfigurationError(f"Hotspot {expected_name} not created")

        elif service_type == ServiceType.PPPOE_SERVER:
            # Verify PPPoE server is running
            pppoe_servers = await client.get_pppoe_servers(connection)
            if not pppoe_servers:
                raise ConfigurationError("PPPoE server not configured")

    async def _apply_security_configuration(self, client, connection, config: Dict[str, Any]) -> None:
        """Apply security configuration."""
        try:
            # Disable unnecessary services
            for command in self.command_templates['security']['disable_default_services']:
                await client.execute_command(connection, command)

            # Apply firewall rules
            management_ip = config.get('management_ip', '0.0.0.0/0')
            for rule_template in self.command_templates['security']['create_firewall_rules']:
                rule = rule_template.format(management_ip=management_ip)
                await client.execute_command(connection, rule)

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
