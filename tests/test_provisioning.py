"""Tests for the provisioning system."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.models.provisioning import (
    ProvisioningSession, 
    ProvisioningStatus, 
    ProvisioningStep,
    ServiceType,
    ProvisioningPriority
)
from app.services.provisioning_service import ProvisioningService
from app.core.exceptions import ProvisioningError, ValidationError


class TestProvisioningService:
    """Test the provisioning service."""

    @pytest.fixture
    async def provisioning_service(self, db_session):
        """Create a provisioning service instance."""
        return ProvisioningService(db_session)

    @pytest.fixture
    async def sample_router(self, db_session):
        """Create a sample router for testing."""
        from app.models.router import Router, RouterType
        
        router = Router(
            name="Test Router",
            ip_address="192.168.1.1",
            username="admin",
            password="password",
            router_type=RouterType.MIKROTIK,
            port=8728
        )
        db_session.add(router)
        await db_session.commit()
        await db_session.refresh(router)
        return router

    @pytest.fixture
    async def sample_user(self, db_session):
        """Create a sample user for testing."""
        from app.models.user import User, UserRole, UserStatus
        
        user = User(
            username="testuser",
            email="test@example.com",
            first_name="Test",
            last_name="User",
            hashed_password="hashed_password",
            role=UserRole.TECHNICIAN,
            status=UserStatus.ACTIVE,
            is_verified=True
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    async def test_create_provisioning_session(
        self, 
        provisioning_service, 
        sample_router, 
        sample_user
    ):
        """Test creating a provisioning session."""
        configuration = {
            "hotspot_name": "Test-Hotspot",
            "ip_pool_start": "172.31.1.1",
            "ip_pool_end": "172.31.1.100",
            "gateway": "172.31.1.1",
            "interface": "ether2"
        }

        session = await provisioning_service.create_provisioning_session(
            router_id=sample_router.id,
            user_id=sample_user.id,
            service_type=ServiceType.HOTSPOT,
            configuration=configuration,
            priority=ProvisioningPriority.NORMAL
        )

        assert session is not None
        assert session.router_id == sample_router.id
        assert session.user_id == sample_user.id
        assert session.service_type == ServiceType.HOTSPOT
        assert session.status == ProvisioningStatus.PENDING
        assert session.current_step == ProvisioningStep.CONNECTION
        assert session.progress_percentage == 0.0
        assert session.session_id is not None

    async def test_validate_configuration_hotspot(self, provisioning_service):
        """Test configuration validation for hotspot."""
        config = {
            "hotspot_name": "Test-Hotspot",
            "interface": "ether2"
        }
        
        validated = await provisioning_service._validate_configuration(
            ServiceType.HOTSPOT, 
            config
        )
        
        assert validated["hotspot_name"] == "Test-Hotspot"
        assert validated["interface"] == "ether2"
        assert "ip_pool_start" in validated
        assert "ip_pool_end" in validated
        assert "gateway" in validated
        assert "dns_servers" in validated

    async def test_validate_configuration_pppoe(self, provisioning_service):
        """Test configuration validation for PPPoE."""
        config = {
            "service_name": "Test-PPPoE",
            "interface": "ether2"
        }
        
        validated = await provisioning_service._validate_configuration(
            ServiceType.PPPOE_SERVER, 
            config
        )
        
        assert validated["service_name"] == "Test-PPPoE"
        assert validated["interface"] == "ether2"
        assert "ip_pool_start" in validated
        assert "ip_pool_end" in validated

    async def test_get_session_status(
        self, 
        provisioning_service, 
        sample_router, 
        sample_user
    ):
        """Test getting session status."""
        # Create a session first
        session = await provisioning_service.create_provisioning_session(
            router_id=sample_router.id,
            user_id=sample_user.id,
            service_type=ServiceType.HOTSPOT,
            configuration={},
            priority=ProvisioningPriority.NORMAL
        )

        status = await provisioning_service.get_session_status(session.session_id)
        
        assert status is not None
        assert status["session_id"] == session.session_id
        assert status["status"] == ProvisioningStatus.PENDING.value
        assert status["current_step"] == ProvisioningStep.CONNECTION.value
        assert status["progress_percentage"] == 0.0
        assert status["steps_completed"] == 0
        assert status["steps_total"] == 3
        assert status["can_cancel"] is True
        assert status["can_retry"] is False

    async def test_duplicate_session_prevention(
        self, 
        provisioning_service, 
        sample_router, 
        sample_user
    ):
        """Test that duplicate sessions are prevented."""
        # Create first session
        await provisioning_service.create_provisioning_session(
            router_id=sample_router.id,
            user_id=sample_user.id,
            service_type=ServiceType.HOTSPOT,
            configuration={},
            priority=ProvisioningPriority.NORMAL
        )

        # Try to create second session for same router
        with pytest.raises(ProvisioningError):
            await provisioning_service.create_provisioning_session(
                router_id=sample_router.id,
                user_id=sample_user.id,
                service_type=ServiceType.PPPOE_SERVER,
                configuration={},
                priority=ProvisioningPriority.NORMAL
            )

    async def test_cancel_provisioning(
        self, 
        provisioning_service, 
        sample_router, 
        sample_user
    ):
        """Test cancelling a provisioning session."""
        session = await provisioning_service.create_provisioning_session(
            router_id=sample_router.id,
            user_id=sample_user.id,
            service_type=ServiceType.HOTSPOT,
            configuration={},
            priority=ProvisioningPriority.NORMAL
        )

        success = await provisioning_service.cancel_provisioning(
            session.session_id,
            reason="Test cancellation"
        )
        
        assert success is True
        
        # Check session status
        updated_session = await provisioning_service.get_session_by_id(session.session_id)
        assert updated_session.status == ProvisioningStatus.CANCELLED

    async def test_generate_configuration_commands(self, provisioning_service):
        """Test generating configuration commands."""
        config = {
            "identity": "Test-Router",
            "bridge_name": "bridge-hotspot",
            "interface": "ether2",
            "ip_pool_start": "172.31.1.1",
            "ip_pool_end": "172.31.1.100",
            "pool_name": "test-pool",
            "dns_servers": ["8.8.8.8", "8.8.4.4"]
        }

        commands = await provisioning_service._generate_configuration_commands(
            config, 
            ServiceType.HOTSPOT
        )
        
        assert len(commands) > 0
        
        # Check for identity command
        identity_cmd = next((cmd for cmd in commands if "identity" in cmd["command"]), None)
        assert identity_cmd is not None
        assert "Test-Router" in identity_cmd["command"]

        # Check for bridge command
        bridge_cmd = next((cmd for cmd in commands if "bridge/add" in cmd["command"]), None)
        assert bridge_cmd is not None
        assert "bridge-hotspot" in bridge_cmd["command"]

    async def test_generate_hotspot_commands(self, provisioning_service):
        """Test generating hotspot-specific commands."""
        config = {
            "hotspot_name": "Test-Hotspot",
            "interface": "ether2",
            "enable_anti_sharing": True,
            "walled_garden_hosts": ["google.com", "facebook.com"]
        }

        commands = await provisioning_service._generate_hotspot_commands(config)
        
        assert len(commands) > 0
        
        # Check for hotspot creation command
        hotspot_cmd = next((cmd for cmd in commands if "hotspot/add" in cmd["command"]), None)
        assert hotspot_cmd is not None
        assert "Test-Hotspot" in hotspot_cmd["command"]

        # Check for anti-sharing command
        anti_share_cmd = next((cmd for cmd in commands if "session-timeout" in cmd["command"]), None)
        assert anti_share_cmd is not None

        # Check for walled garden commands
        walled_garden_cmds = [cmd for cmd in commands if "walled-garden" in cmd["command"]]
        assert len(walled_garden_cmds) == 2

    async def test_generate_pppoe_commands(self, provisioning_service):
        """Test generating PPPoE-specific commands."""
        config = {
            "service_name": "Test-PPPoE",
            "interface": "ether2",
            "profile_name": "test-profile",
            "gateway": "172.31.1.1",
            "pool_name": "test-pool"
        }

        commands = await provisioning_service._generate_pppoe_commands(config)
        
        assert len(commands) > 0
        
        # Check for PPP profile command
        profile_cmd = next((cmd for cmd in commands if "ppp/profile/add" in cmd["command"]), None)
        assert profile_cmd is not None
        assert "test-profile" in profile_cmd["command"]

        # Check for PPPoE server command
        server_cmd = next((cmd for cmd in commands if "pppoe-server/server/add" in cmd["command"]), None)
        assert server_cmd is not None
        assert "Test-PPPoE" in server_cmd["command"]


class TestProvisioningAPI:
    """Test the provisioning API endpoints."""

    async def test_start_provisioning_workflow(self, client, admin_headers):
        """Test starting a provisioning workflow."""
        # First create a router
        router_data = {
            "name": "Test Router",
            "ip_address": "192.168.1.1",
            "username": "admin",
            "password": "password",
            "router_type": "mikrotik",
            "port": 8728
        }
        
        router_response = await client.post(
            "/api/v1/routers/",
            json=router_data,
            headers=admin_headers
        )
        assert router_response.status_code == 201
        router = router_response.json()

        # Start provisioning workflow
        workflow_data = {
            "router_id": router["id"],
            "service_type": "hotspot",
            "configuration": {
                "hotspot_name": "Test-Hotspot",
                "interface": "ether2"
            },
            "priority": "normal",
            "auto_start": False  # Don't actually start for test
        }

        response = await client.post(
            "/api/v1/provisioning/workflow",
            json=workflow_data,
            headers=admin_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["status"] == "pending"
        assert "estimated_duration_minutes" in data

    async def test_get_provisioning_sessions(self, client, admin_headers):
        """Test getting provisioning sessions."""
        response = await client.get(
            "/api/v1/provisioning/sessions",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "size" in data

    async def test_get_service_types(self, client, admin_headers):
        """Test getting available service types."""
        response = await client.get(
            "/api/v1/provisioning/service-types",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert all("value" in item and "label" in item for item in data)

    async def test_get_default_configuration(self, client, admin_headers):
        """Test getting default configuration."""
        response = await client.get(
            "/api/v1/provisioning/default-configuration/hotspot",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "service_type" in data
        assert "configuration" in data
        assert data["service_type"] == "hotspot"

    async def test_validate_configuration(self, client, admin_headers):
        """Test configuration validation."""
        validation_data = {
            "hotspot_name": "Test-Hotspot",
            "interface": "ether2"
        }

        response = await client.post(
            "/api/v1/provisioning/validate-configuration?service_type=hotspot",
            json=validation_data,
            headers=admin_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "valid" in data
        assert data["valid"] is True
        assert "configuration" in data

    async def test_get_provisioning_stats(self, client, admin_headers):
        """Test getting provisioning statistics."""
        response = await client.get(
            "/api/v1/provisioning/stats?days=30",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "period_days" in data
        assert "total_sessions" in data
        assert "success_rate" in data
        assert "status_breakdown" in data
