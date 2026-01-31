"""
Comprehensive MikroTik Router Provisioning Tests for ISP Billing System

This test suite validates all aspects of MikroTik router provisioning including:
- Router connectivity and API access
- Hotspot server configuration and user management
- PPPoE server configuration and user management
- Bandwidth management and queue configuration
- Captive portal and walled garden
- User authentication and access control
- Package expiry and automatic disconnection
- Usage tracking and accounting

Target Router: http://192.168.100.7/ (MikroTik RouterOS)

Prerequisites:
- MikroTik router accessible at 192.168.100.7
- API enabled on port 8728
- Admin credentials configured
- routeros-api library installed: pip install routeros-api

Usage:
    pytest tests/mikrotik_provisioning_test.py -v
    python tests/mikrotik_provisioning_test.py  # Run directly
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum
import hashlib
import secrets
import string

import pytest
import routeros_api

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class RouterConfig:
    """MikroTik router configuration."""
    ip_address: str = "192.168.100.7"
    port: int = 8728
    username: str = "admin"
    password: str = ""  # Set your router password
    use_ssl: bool = False


@dataclass
class TestConfig:
    """Test configuration."""
    # Test user prefix (for cleanup)
    test_prefix: str = "test_"

    # Hotspot configuration
    hotspot_interface: str = "ether2"
    hotspot_bridge: str = "bridge-hotspot"
    hotspot_pool_name: str = "hotspot-pool"
    hotspot_pool_range: str = "172.31.1.100-172.31.1.200"
    hotspot_gateway: str = "172.31.1.1"
    hotspot_netmask: str = "24"

    # PPPoE configuration
    pppoe_interface: str = "ether3"
    pppoe_service_name: str = "ISP-PPPoE"
    pppoe_pool_name: str = "pppoe-pool"
    pppoe_pool_range: str = "172.32.1.100-172.32.1.200"
    pppoe_gateway: str = "172.32.1.1"

    # Bandwidth profiles (in kbps)
    bandwidth_profiles: Dict[str, Dict[str, int]] = None

    def __post_init__(self):
        if self.bandwidth_profiles is None:
            self.bandwidth_profiles = {
                "basic": {"download": 2048, "upload": 1024},      # 2Mbps/1Mbps
                "standard": {"download": 5120, "upload": 2048},   # 5Mbps/2Mbps
                "premium": {"download": 10240, "upload": 5120},   # 10Mbps/5Mbps
                "unlimited": {"download": 0, "upload": 0},        # No limit
            }


class ServiceType(Enum):
    """Service type enumeration."""
    HOTSPOT = "hotspot"
    PPPOE = "pppoe"


# =============================================================================
# MIKROTIK CLIENT
# =============================================================================

class MikroTikTestClient:
    """MikroTik API client for testing."""

    def __init__(self, config: RouterConfig):
        self.config = config
        self.connection: Optional[routeros_api.RouterOsApiPool] = None
        self.api = None

    def connect(self) -> bool:
        """Connect to the MikroTik router."""
        try:
            self.connection = routeros_api.RouterOsApiPool(
                self.config.ip_address,
                username=self.config.username,
                password=self.config.password,
                port=self.config.port,
                use_ssl=self.config.use_ssl,
                plaintext_login=True,
            )
            self.api = self.connection.get_api()
            logger.info(f"Connected to MikroTik router at {self.config.ip_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to router: {e}")
            return False

    def disconnect(self):
        """Disconnect from the router."""
        if self.connection:
            try:
                self.connection.disconnect()
                logger.info("Disconnected from MikroTik router")
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")

    def get_resource(self, path: str):
        """Get API resource."""
        return self.api.get_resource(path)

    def execute(self, path: str, method: str = "get", **params) -> List[Dict[str, Any]]:
        """Execute API command."""
        resource = self.get_resource(path)

        if method == "get":
            return resource.get(**params) if params else resource.get()
        elif method == "add":
            return resource.add(**params)
        elif method == "set":
            return resource.set(**params)
        elif method == "remove":
            return resource.remove(**params)
        elif method == "call":
            cmd = params.pop("cmd", "print")
            return resource.call(cmd, params)
        else:
            raise ValueError(f"Unknown method: {method}")


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture(scope="module")
def router_config():
    """Router configuration fixture."""
    return RouterConfig()


@pytest.fixture(scope="module")
def test_config():
    """Test configuration fixture."""
    return TestConfig()


@pytest.fixture(scope="module")
def mikrotik_client(router_config):
    """MikroTik client fixture."""
    client = MikroTikTestClient(router_config)
    if not client.connect():
        pytest.skip("Could not connect to MikroTik router")
    yield client
    client.disconnect()


@pytest.fixture
def test_username():
    """Generate unique test username."""
    random_suffix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"test_{random_suffix}"


@pytest.fixture
def test_password():
    """Generate test password."""
    return secrets.token_urlsafe(12)


# =============================================================================
# TEST CLASSES
# =============================================================================

class TestRouterConnectivity:
    """Test router connectivity and basic operations."""

    def test_connect_to_router(self, mikrotik_client):
        """Test basic connection to router."""
        assert mikrotik_client.api is not None
        logger.info("✓ Successfully connected to MikroTik router")

    def test_get_system_info(self, mikrotik_client):
        """Test retrieving system information."""
        result = mikrotik_client.execute("/system/resource")

        assert len(result) > 0
        system_info = result[0]

        # Verify expected fields
        assert "version" in system_info
        assert "cpu-load" in system_info
        assert "free-memory" in system_info
        assert "uptime" in system_info

        logger.info(f"✓ RouterOS Version: {system_info.get('version')}")
        logger.info(f"✓ CPU Load: {system_info.get('cpu-load')}%")
        logger.info(f"✓ Free Memory: {int(system_info.get('free-memory', 0)) / 1024 / 1024:.1f} MB")
        logger.info(f"✓ Uptime: {system_info.get('uptime')}")

    def test_get_system_identity(self, mikrotik_client):
        """Test retrieving system identity."""
        result = mikrotik_client.execute("/system/identity")

        assert len(result) > 0
        identity = result[0]
        assert "name" in identity

        logger.info(f"✓ System Identity: {identity.get('name')}")

    def test_get_interfaces(self, mikrotik_client):
        """Test retrieving network interfaces."""
        result = mikrotik_client.execute("/interface")

        assert len(result) > 0

        interface_names = [iface.get("name") for iface in result]
        logger.info(f"✓ Found {len(result)} interfaces: {', '.join(interface_names)}")

        # Check for common interfaces
        for iface in result:
            logger.debug(f"  - {iface.get('name')}: {iface.get('type')} ({iface.get('running', 'unknown')})")

    def test_api_port_enabled(self, mikrotik_client):
        """Test that API service is enabled."""
        result = mikrotik_client.execute("/ip/service")

        api_service = next((s for s in result if s.get("name") == "api"), None)

        assert api_service is not None
        assert api_service.get("disabled") == "false"

        logger.info(f"✓ API service enabled on port {api_service.get('port')}")


class TestIPPoolManagement:
    """Test IP pool configuration for DHCP/PPPoE."""

    def test_create_ip_pool(self, mikrotik_client, test_config):
        """Test creating an IP pool."""
        pool_name = f"{test_config.test_prefix}pool"

        # Remove if exists
        try:
            existing = mikrotik_client.execute("/ip/pool", name=pool_name)
            if existing:
                mikrotik_client.execute("/ip/pool", method="remove", id=existing[0][".id"])
        except:
            pass

        # Create pool
        mikrotik_client.execute(
            "/ip/pool",
            method="add",
            name=pool_name,
            ranges="192.168.200.100-192.168.200.200"
        )

        # Verify
        result = mikrotik_client.execute("/ip/pool")
        pool = next((p for p in result if p.get("name") == pool_name), None)

        assert pool is not None
        assert pool.get("ranges") == "192.168.200.100-192.168.200.200"

        logger.info(f"✓ Created IP pool: {pool_name}")

        # Cleanup
        mikrotik_client.execute("/ip/pool", method="remove", id=pool[".id"])
        logger.info(f"✓ Cleaned up IP pool: {pool_name}")

    def test_list_ip_pools(self, mikrotik_client):
        """Test listing all IP pools."""
        result = mikrotik_client.execute("/ip/pool")

        logger.info(f"✓ Found {len(result)} IP pools:")
        for pool in result:
            logger.info(f"  - {pool.get('name')}: {pool.get('ranges')}")


class TestHotspotProvisioning:
    """Test Hotspot server provisioning and management."""

    def test_list_hotspot_servers(self, mikrotik_client):
        """Test listing hotspot servers."""
        result = mikrotik_client.execute("/ip/hotspot")

        logger.info(f"✓ Found {len(result)} hotspot servers:")
        for hs in result:
            logger.info(f"  - {hs.get('name')}: interface={hs.get('interface')}, disabled={hs.get('disabled')}")

    def test_list_hotspot_profiles(self, mikrotik_client):
        """Test listing hotspot profiles."""
        result = mikrotik_client.execute("/ip/hotspot/profile")

        logger.info(f"✓ Found {len(result)} hotspot profiles:")
        for profile in result:
            logger.info(f"  - {profile.get('name')}: rate-limit={profile.get('rate-limit', 'none')}")

    def test_create_hotspot_user(self, mikrotik_client, test_username, test_password):
        """Test creating a hotspot user."""
        # Create user
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="add",
            name=test_username,
            password=test_password,
            profile="default"
        )

        # Verify
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)

        assert user is not None
        assert user.get("profile") == "default"

        logger.info(f"✓ Created hotspot user: {test_username}")

        # Cleanup
        mikrotik_client.execute("/ip/hotspot/user", method="remove", id=user[".id"])
        logger.info(f"✓ Cleaned up hotspot user: {test_username}")

    def test_create_hotspot_user_with_limits(self, mikrotik_client, test_username, test_password):
        """Test creating a hotspot user with bandwidth and data limits."""
        # Create user with limits
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="add",
            name=test_username,
            password=test_password,
            profile="default",
            **{
                "limit-uptime": "1h",
                "limit-bytes-total": "104857600"  # 100MB
            }
        )

        # Verify
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)

        assert user is not None
        assert user.get("limit-uptime") == "1h"
        assert user.get("limit-bytes-total") == "104857600"

        logger.info(f"✓ Created hotspot user with limits: {test_username}")
        logger.info(f"  - Time limit: {user.get('limit-uptime')}")
        logger.info(f"  - Data limit: {int(user.get('limit-bytes-total', 0)) / 1024 / 1024:.0f} MB")

        # Cleanup
        mikrotik_client.execute("/ip/hotspot/user", method="remove", id=user[".id"])

    def test_disable_hotspot_user(self, mikrotik_client, test_username, test_password):
        """Test disabling/enabling a hotspot user (simulating expiry)."""
        # Create user
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="add",
            name=test_username,
            password=test_password,
            profile="default"
        )

        # Get user
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)
        user_id = user[".id"]

        # Disable user (simulate package expiry)
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="set",
            id=user_id,
            disabled="yes"
        )

        # Verify disabled
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)
        assert user.get("disabled") == "true"

        logger.info(f"✓ Disabled hotspot user: {test_username}")

        # Re-enable user (simulate renewal)
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="set",
            id=user_id,
            disabled="no"
        )

        # Verify enabled
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)
        assert user.get("disabled") == "false"

        logger.info(f"✓ Re-enabled hotspot user: {test_username}")

        # Cleanup
        mikrotik_client.execute("/ip/hotspot/user", method="remove", id=user_id)

    def test_list_active_hotspot_sessions(self, mikrotik_client):
        """Test listing active hotspot sessions."""
        result = mikrotik_client.execute("/ip/hotspot/active")

        logger.info(f"✓ Found {len(result)} active hotspot sessions:")
        for session in result:
            logger.info(f"  - User: {session.get('user')}, IP: {session.get('address')}, "
                       f"Uptime: {session.get('uptime')}, Bytes: {session.get('bytes-in')}/{session.get('bytes-out')}")

    def test_walled_garden_configuration(self, mikrotik_client):
        """Test walled garden (allow access without authentication)."""
        # List current walled garden entries
        result = mikrotik_client.execute("/ip/hotspot/walled-garden")

        logger.info(f"✓ Found {len(result)} walled garden entries:")
        for entry in result:
            logger.info(f"  - {entry.get('dst-host', entry.get('dst-port', 'unknown'))}")

        # Add test entry
        test_host = "test-portal.example.com"
        mikrotik_client.execute(
            "/ip/hotspot/walled-garden",
            method="add",
            **{"dst-host": test_host}
        )

        # Verify
        result = mikrotik_client.execute("/ip/hotspot/walled-garden")
        entry = next((e for e in result if e.get("dst-host") == test_host), None)

        assert entry is not None
        logger.info(f"✓ Added walled garden entry: {test_host}")

        # Cleanup
        mikrotik_client.execute("/ip/hotspot/walled-garden", method="remove", id=entry[".id"])
        logger.info(f"✓ Removed walled garden entry: {test_host}")


class TestPPPoEProvisioning:
    """Test PPPoE server provisioning and management."""

    def test_list_pppoe_servers(self, mikrotik_client):
        """Test listing PPPoE servers."""
        result = mikrotik_client.execute("/interface/pppoe-server/server")

        logger.info(f"✓ Found {len(result)} PPPoE servers:")
        for server in result:
            logger.info(f"  - {server.get('service-name')}: interface={server.get('interface')}, "
                       f"disabled={server.get('disabled')}")

    def test_list_ppp_profiles(self, mikrotik_client):
        """Test listing PPP profiles."""
        result = mikrotik_client.execute("/ppp/profile")

        logger.info(f"✓ Found {len(result)} PPP profiles:")
        for profile in result:
            logger.info(f"  - {profile.get('name')}: local={profile.get('local-address')}, "
                       f"remote={profile.get('remote-address')}, rate-limit={profile.get('rate-limit', 'none')}")

    def test_create_ppp_profile_with_bandwidth(self, mikrotik_client, test_config):
        """Test creating a PPP profile with bandwidth limits."""
        profile_name = f"{test_config.test_prefix}profile_5mbps"

        # Remove if exists
        try:
            existing = mikrotik_client.execute("/ppp/profile")
            existing_profile = next((p for p in existing if p.get("name") == profile_name), None)
            if existing_profile:
                mikrotik_client.execute("/ppp/profile", method="remove", id=existing_profile[".id"])
        except:
            pass

        # Create profile with rate limit (format: rx/tx)
        mikrotik_client.execute(
            "/ppp/profile",
            method="add",
            name=profile_name,
            **{
                "local-address": "172.32.1.1",
                "rate-limit": "5M/2M"  # 5Mbps download / 2Mbps upload
            }
        )

        # Verify
        result = mikrotik_client.execute("/ppp/profile")
        profile = next((p for p in result if p.get("name") == profile_name), None)

        assert profile is not None
        assert profile.get("rate-limit") == "5M/2M"

        logger.info(f"✓ Created PPP profile with bandwidth: {profile_name}")
        logger.info(f"  - Rate limit: {profile.get('rate-limit')}")

        # Cleanup
        mikrotik_client.execute("/ppp/profile", method="remove", id=profile[".id"])
        logger.info(f"✓ Cleaned up PPP profile: {profile_name}")

    def test_create_pppoe_user(self, mikrotik_client, test_username, test_password):
        """Test creating a PPPoE user (secret)."""
        # Create PPPoE user/secret
        mikrotik_client.execute(
            "/ppp/secret",
            method="add",
            name=test_username,
            password=test_password,
            service="pppoe",
            profile="default"
        )

        # Verify
        result = mikrotik_client.execute("/ppp/secret")
        user = next((u for u in result if u.get("name") == test_username), None)

        assert user is not None
        assert user.get("service") == "pppoe"
        assert user.get("profile") == "default"

        logger.info(f"✓ Created PPPoE user: {test_username}")

        # Cleanup
        mikrotik_client.execute("/ppp/secret", method="remove", id=user[".id"])
        logger.info(f"✓ Cleaned up PPPoE user: {test_username}")

    def test_create_pppoe_user_with_static_ip(self, mikrotik_client, test_username, test_password):
        """Test creating a PPPoE user with static IP assignment."""
        static_ip = "172.32.1.50"

        # Create PPPoE user with static IP
        mikrotik_client.execute(
            "/ppp/secret",
            method="add",
            name=test_username,
            password=test_password,
            service="pppoe",
            profile="default",
            **{
                "remote-address": static_ip
            }
        )

        # Verify
        result = mikrotik_client.execute("/ppp/secret")
        user = next((u for u in result if u.get("name") == test_username), None)

        assert user is not None
        assert user.get("remote-address") == static_ip

        logger.info(f"✓ Created PPPoE user with static IP: {test_username} -> {static_ip}")

        # Cleanup
        mikrotik_client.execute("/ppp/secret", method="remove", id=user[".id"])

    def test_disable_pppoe_user(self, mikrotik_client, test_username, test_password):
        """Test disabling/enabling a PPPoE user (simulating expiry)."""
        # Create user
        mikrotik_client.execute(
            "/ppp/secret",
            method="add",
            name=test_username,
            password=test_password,
            service="pppoe",
            profile="default"
        )

        # Get user
        result = mikrotik_client.execute("/ppp/secret")
        user = next((u for u in result if u.get("name") == test_username), None)
        user_id = user[".id"]

        # Disable user (simulate package expiry)
        mikrotik_client.execute(
            "/ppp/secret",
            method="set",
            id=user_id,
            disabled="yes"
        )

        # Verify disabled
        result = mikrotik_client.execute("/ppp/secret")
        user = next((u for u in result if u.get("name") == test_username), None)
        assert user.get("disabled") == "true"

        logger.info(f"✓ Disabled PPPoE user: {test_username}")

        # Re-enable user (simulate renewal)
        mikrotik_client.execute(
            "/ppp/secret",
            method="set",
            id=user_id,
            disabled="no"
        )

        logger.info(f"✓ Re-enabled PPPoE user: {test_username}")

        # Cleanup
        mikrotik_client.execute("/ppp/secret", method="remove", id=user_id)

    def test_list_active_pppoe_sessions(self, mikrotik_client):
        """Test listing active PPPoE sessions."""
        result = mikrotik_client.execute("/ppp/active")

        logger.info(f"✓ Found {len(result)} active PPPoE sessions:")
        for session in result:
            logger.info(f"  - User: {session.get('name')}, Service: {session.get('service')}, "
                       f"Address: {session.get('address')}, Uptime: {session.get('uptime')}")


class TestBandwidthManagement:
    """Test bandwidth management and queue configuration."""

    def test_list_simple_queues(self, mikrotik_client):
        """Test listing simple queues."""
        result = mikrotik_client.execute("/queue/simple")

        logger.info(f"✓ Found {len(result)} simple queues:")
        for queue in result:
            logger.info(f"  - {queue.get('name')}: target={queue.get('target')}, "
                       f"max-limit={queue.get('max-limit')}")

    def test_create_simple_queue(self, mikrotik_client, test_config):
        """Test creating a simple queue for bandwidth limiting."""
        queue_name = f"{test_config.test_prefix}queue"
        target_ip = "192.168.100.50/32"

        # Remove if exists
        try:
            existing = mikrotik_client.execute("/queue/simple")
            existing_queue = next((q for q in existing if q.get("name") == queue_name), None)
            if existing_queue:
                mikrotik_client.execute("/queue/simple", method="remove", id=existing_queue[".id"])
        except:
            pass

        # Create queue with 5Mbps/2Mbps limit
        mikrotik_client.execute(
            "/queue/simple",
            method="add",
            name=queue_name,
            target=target_ip,
            **{
                "max-limit": "5M/2M",
                "burst-limit": "6M/3M",
                "burst-threshold": "4M/1M",
                "burst-time": "10s/10s"
            }
        )

        # Verify
        result = mikrotik_client.execute("/queue/simple")
        queue = next((q for q in result if q.get("name") == queue_name), None)

        assert queue is not None
        assert queue.get("max-limit") == "5M/2M"

        logger.info(f"✓ Created simple queue: {queue_name}")
        logger.info(f"  - Target: {queue.get('target')}")
        logger.info(f"  - Max limit: {queue.get('max-limit')}")
        logger.info(f"  - Burst limit: {queue.get('burst-limit')}")

        # Cleanup
        mikrotik_client.execute("/queue/simple", method="remove", id=queue[".id"])
        logger.info(f"✓ Cleaned up queue: {queue_name}")

    def test_list_queue_types(self, mikrotik_client):
        """Test listing queue types (PCQ, etc.)."""
        result = mikrotik_client.execute("/queue/type")

        logger.info(f"✓ Found {len(result)} queue types:")
        for qtype in result:
            logger.info(f"  - {qtype.get('name')}: kind={qtype.get('kind')}")

    def test_hotspot_profile_rate_limit(self, mikrotik_client, test_config):
        """Test creating a hotspot profile with rate limit."""
        profile_name = f"{test_config.test_prefix}hotspot_profile"

        # Remove if exists
        try:
            existing = mikrotik_client.execute("/ip/hotspot/user/profile")
            existing_profile = next((p for p in existing if p.get("name") == profile_name), None)
            if existing_profile:
                mikrotik_client.execute("/ip/hotspot/user/profile", method="remove", id=existing_profile[".id"])
        except:
            pass

        # Create hotspot user profile with rate limit
        mikrotik_client.execute(
            "/ip/hotspot/user/profile",
            method="add",
            name=profile_name,
            **{
                "rate-limit": "5M/2M",  # 5Mbps download / 2Mbps upload
                "session-timeout": "1d",
                "idle-timeout": "5m",
                "shared-users": "1"  # Anti-sharing: 1 device per user
            }
        )

        # Verify
        result = mikrotik_client.execute("/ip/hotspot/user/profile")
        profile = next((p for p in result if p.get("name") == profile_name), None)

        assert profile is not None
        assert profile.get("rate-limit") == "5M/2M"
        assert profile.get("shared-users") == "1"

        logger.info(f"✓ Created hotspot user profile: {profile_name}")
        logger.info(f"  - Rate limit: {profile.get('rate-limit')}")
        logger.info(f"  - Shared users: {profile.get('shared-users')}")

        # Cleanup
        mikrotik_client.execute("/ip/hotspot/user/profile", method="remove", id=profile[".id"])


class TestCaptivePortalConfiguration:
    """Test captive portal configuration and behavior."""

    def test_hotspot_html_directory(self, mikrotik_client):
        """Test listing hotspot HTML files for customization."""
        try:
            result = mikrotik_client.execute("/file")

            hotspot_files = [f for f in result if "hotspot" in f.get("name", "").lower()]

            logger.info(f"✓ Found {len(hotspot_files)} hotspot-related files:")
            for f in hotspot_files:
                logger.info(f"  - {f.get('name')}: size={f.get('size')} bytes")
        except Exception as e:
            logger.warning(f"Could not list files: {e}")

    def test_hotspot_server_profile(self, mikrotik_client):
        """Test hotspot server profile configuration."""
        result = mikrotik_client.execute("/ip/hotspot/profile")

        logger.info(f"✓ Found {len(result)} hotspot server profiles:")
        for profile in result:
            logger.info(f"  - {profile.get('name')}:")
            logger.info(f"      HTML directory: {profile.get('html-directory', 'default')}")
            logger.info(f"      Login by: {profile.get('login-by', 'unknown')}")
            logger.info(f"      HTTP cookie: {profile.get('http-cookie-lifetime', 'unknown')}")

    def test_list_walled_garden_ip(self, mikrotik_client):
        """Test IP-based walled garden (allows specific IPs without auth)."""
        result = mikrotik_client.execute("/ip/hotspot/walled-garden/ip")

        logger.info(f"✓ Found {len(result)} IP walled garden entries:")
        for entry in result:
            logger.info(f"  - {entry.get('dst-address', 'any')} -> {entry.get('action', 'accept')}")


class TestUserSessionManagement:
    """Test user session tracking and management."""

    def test_disconnect_active_hotspot_user(self, mikrotik_client, test_username, test_password):
        """Test disconnecting an active hotspot user."""
        # Create user
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="add",
            name=test_username,
            password=test_password,
            profile="default"
        )

        # Check for active session (may not exist if user hasn't logged in)
        active_sessions = mikrotik_client.execute("/ip/hotspot/active")
        user_session = next((s for s in active_sessions if s.get("user") == test_username), None)

        if user_session:
            # Disconnect user
            mikrotik_client.execute(
                "/ip/hotspot/active",
                method="remove",
                id=user_session[".id"]
            )
            logger.info(f"✓ Disconnected active hotspot session for: {test_username}")
        else:
            logger.info(f"✓ No active session found for: {test_username} (user not connected)")

        # Cleanup user
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)
        if user:
            mikrotik_client.execute("/ip/hotspot/user", method="remove", id=user[".id"])

    def test_disconnect_active_pppoe_user(self, mikrotik_client, test_username, test_password):
        """Test disconnecting an active PPPoE user."""
        # Create user
        mikrotik_client.execute(
            "/ppp/secret",
            method="add",
            name=test_username,
            password=test_password,
            service="pppoe",
            profile="default"
        )

        # Check for active session
        active_sessions = mikrotik_client.execute("/ppp/active")
        user_session = next((s for s in active_sessions if s.get("name") == test_username), None)

        if user_session:
            # Disconnect user
            mikrotik_client.execute(
                "/ppp/active",
                method="remove",
                id=user_session[".id"]
            )
            logger.info(f"✓ Disconnected active PPPoE session for: {test_username}")
        else:
            logger.info(f"✓ No active session found for: {test_username} (user not connected)")

        # Cleanup user
        result = mikrotik_client.execute("/ppp/secret")
        user = next((u for u in result if u.get("name") == test_username), None)
        if user:
            mikrotik_client.execute("/ppp/secret", method="remove", id=user[".id"])

    def test_get_user_usage_stats(self, mikrotik_client):
        """Test getting usage statistics from active sessions."""
        # Get hotspot active users with stats
        hotspot_active = mikrotik_client.execute("/ip/hotspot/active")

        logger.info("✓ Hotspot user statistics:")
        for user in hotspot_active:
            bytes_in = int(user.get("bytes-in", 0))
            bytes_out = int(user.get("bytes-out", 0))
            logger.info(f"  - {user.get('user')}: "
                       f"Download: {bytes_in / 1024 / 1024:.2f} MB, "
                       f"Upload: {bytes_out / 1024 / 1024:.2f} MB, "
                       f"Uptime: {user.get('uptime')}")

        # Get PPPoE active users with stats
        pppoe_active = mikrotik_client.execute("/ppp/active")

        logger.info("✓ PPPoE user statistics:")
        for user in pppoe_active:
            logger.info(f"  - {user.get('name')}: "
                       f"Address: {user.get('address')}, "
                       f"Uptime: {user.get('uptime')}, "
                       f"Caller-ID: {user.get('caller-id', 'unknown')}")


class TestPackageExpiryManagement:
    """Test package expiry and automatic user disconnection."""

    def test_hotspot_user_expiry_workflow(self, mikrotik_client, test_username, test_password):
        """Test complete workflow for hotspot user expiry."""
        logger.info(f"Testing hotspot user expiry workflow for: {test_username}")

        # 1. Create user with active subscription
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="add",
            name=test_username,
            password=test_password,
            profile="default",
            **{
                "limit-uptime": "1h",  # 1 hour limit
                "comment": f"Expires: {datetime.utcnow() + timedelta(hours=1)}"
            }
        )
        logger.info(f"  1. Created user with 1 hour limit")

        # 2. Verify user is active
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)
        assert user.get("disabled") == "false"
        logger.info(f"  2. Verified user is active")

        # 3. Simulate package expiry (disable user)
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="set",
            id=user[".id"],
            disabled="yes",
            comment=f"Expired: {datetime.utcnow()}"
        )
        logger.info(f"  3. Simulated package expiry (disabled user)")

        # 4. Verify user is disabled
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)
        assert user.get("disabled") == "true"
        logger.info(f"  4. Verified user is disabled")

        # 5. Simulate package renewal (re-enable user with new limits)
        mikrotik_client.execute(
            "/ip/hotspot/user",
            method="set",
            id=user[".id"],
            disabled="no",
            **{
                "limit-uptime": "24h",
                "limit-bytes-total": "0",  # Reset counters
                "comment": f"Renewed: {datetime.utcnow()}, Expires: {datetime.utcnow() + timedelta(days=1)}"
            }
        )
        logger.info(f"  5. Simulated package renewal (re-enabled with new limits)")

        # 6. Verify user is active again
        result = mikrotik_client.execute("/ip/hotspot/user")
        user = next((u for u in result if u.get("name") == test_username), None)
        assert user.get("disabled") == "false"
        logger.info(f"  6. Verified user is active again")

        # Cleanup
        mikrotik_client.execute("/ip/hotspot/user", method="remove", id=user[".id"])
        logger.info(f"  ✓ Workflow completed successfully")

    def test_pppoe_user_expiry_workflow(self, mikrotik_client, test_username, test_password):
        """Test complete workflow for PPPoE user expiry."""
        logger.info(f"Testing PPPoE user expiry workflow for: {test_username}")

        # 1. Create user with active subscription
        mikrotik_client.execute(
            "/ppp/secret",
            method="add",
            name=test_username,
            password=test_password,
            service="pppoe",
            profile="default",
            comment=f"Expires: {datetime.utcnow() + timedelta(days=30)}"
        )
        logger.info(f"  1. Created PPPoE user")

        # 2. Verify user is active
        result = mikrotik_client.execute("/ppp/secret")
        user = next((u for u in result if u.get("name") == test_username), None)
        assert user.get("disabled") == "false"
        logger.info(f"  2. Verified user is active")

        # 3. Simulate package expiry
        mikrotik_client.execute(
            "/ppp/secret",
            method="set",
            id=user[".id"],
            disabled="yes",
            comment=f"Expired: {datetime.utcnow()}"
        )
        logger.info(f"  3. Simulated package expiry")

        # 4. Check and disconnect any active session
        active = mikrotik_client.execute("/ppp/active")
        session = next((s for s in active if s.get("name") == test_username), None)
        if session:
            mikrotik_client.execute("/ppp/active", method="remove", id=session[".id"])
            logger.info(f"  4. Disconnected active session")
        else:
            logger.info(f"  4. No active session to disconnect")

        # 5. Simulate renewal
        mikrotik_client.execute(
            "/ppp/secret",
            method="set",
            id=user[".id"],
            disabled="no",
            comment=f"Renewed: {datetime.utcnow()}, Expires: {datetime.utcnow() + timedelta(days=30)}"
        )
        logger.info(f"  5. Simulated package renewal")

        # Cleanup
        result = mikrotik_client.execute("/ppp/secret")
        user = next((u for u in result if u.get("name") == test_username), None)
        mikrotik_client.execute("/ppp/secret", method="remove", id=user[".id"])
        logger.info(f"  ✓ Workflow completed successfully")


class TestFirewallAndNAT:
    """Test firewall and NAT configuration for captive portal."""

    def test_list_nat_rules(self, mikrotik_client):
        """Test listing NAT rules."""
        result = mikrotik_client.execute("/ip/firewall/nat")

        logger.info(f"✓ Found {len(result)} NAT rules:")
        for rule in result[:10]:  # Show first 10
            logger.info(f"  - Chain: {rule.get('chain')}, Action: {rule.get('action')}, "
                       f"Dst-port: {rule.get('dst-port', 'any')}")

    def test_list_filter_rules(self, mikrotik_client):
        """Test listing firewall filter rules."""
        result = mikrotik_client.execute("/ip/firewall/filter")

        logger.info(f"✓ Found {len(result)} filter rules:")
        for rule in result[:10]:  # Show first 10
            logger.info(f"  - Chain: {rule.get('chain')}, Action: {rule.get('action')}, "
                       f"Comment: {rule.get('comment', 'none')[:50]}")

    def test_list_mangle_rules(self, mikrotik_client):
        """Test listing mangle rules (for traffic shaping)."""
        result = mikrotik_client.execute("/ip/firewall/mangle")

        logger.info(f"✓ Found {len(result)} mangle rules:")
        for rule in result[:10]:  # Show first 10
            logger.info(f"  - Chain: {rule.get('chain')}, Action: {rule.get('action')}, "
                       f"New packet mark: {rule.get('new-packet-mark', 'none')}")


class TestDHCPConfiguration:
    """Test DHCP server configuration for hotspot."""

    def test_list_dhcp_servers(self, mikrotik_client):
        """Test listing DHCP servers."""
        result = mikrotik_client.execute("/ip/dhcp-server")

        logger.info(f"✓ Found {len(result)} DHCP servers:")
        for server in result:
            logger.info(f"  - {server.get('name')}: interface={server.get('interface')}, "
                       f"address-pool={server.get('address-pool')}, disabled={server.get('disabled')}")

    def test_list_dhcp_leases(self, mikrotik_client):
        """Test listing active DHCP leases."""
        result = mikrotik_client.execute("/ip/dhcp-server/lease")

        logger.info(f"✓ Found {len(result)} DHCP leases:")
        for lease in result[:10]:  # Show first 10
            logger.info(f"  - IP: {lease.get('address')}, MAC: {lease.get('mac-address')}, "
                       f"Status: {lease.get('status')}, Host: {lease.get('host-name', 'unknown')}")


class TestIntegrationScenarios:
    """Integration test scenarios simulating real ISP operations."""

    def test_complete_hotspot_provisioning_flow(self, mikrotik_client, test_config):
        """Test complete hotspot provisioning from scratch."""
        logger.info("=" * 60)
        logger.info("INTEGRATION TEST: Complete Hotspot Provisioning")
        logger.info("=" * 60)

        prefix = f"{test_config.test_prefix}int_"
        pool_name = f"{prefix}pool"
        profile_name = f"{prefix}profile"
        user_name = f"{prefix}user"

        try:
            # Step 1: Create IP pool
            logger.info("Step 1: Creating IP pool...")
            mikrotik_client.execute(
                "/ip/pool",
                method="add",
                name=pool_name,
                ranges="192.168.250.100-192.168.250.200"
            )
            logger.info(f"  ✓ Created pool: {pool_name}")

            # Step 2: Create hotspot user profile with bandwidth
            logger.info("Step 2: Creating hotspot user profile...")
            mikrotik_client.execute(
                "/ip/hotspot/user/profile",
                method="add",
                name=profile_name,
                **{
                    "rate-limit": "5M/2M",
                    "shared-users": "1",
                    "session-timeout": "1d"
                }
            )
            logger.info(f"  ✓ Created profile: {profile_name} (5Mbps/2Mbps)")

            # Step 3: Create test user
            logger.info("Step 3: Creating hotspot user...")
            mikrotik_client.execute(
                "/ip/hotspot/user",
                method="add",
                name=user_name,
                password="testpass123",
                profile=profile_name,
                **{
                    "limit-uptime": "24h",
                    "limit-bytes-total": "1073741824"  # 1GB
                }
            )
            logger.info(f"  ✓ Created user: {user_name} (1GB data, 24h time)")

            # Step 4: Verify configuration
            logger.info("Step 4: Verifying configuration...")

            pools = mikrotik_client.execute("/ip/pool")
            assert any(p.get("name") == pool_name for p in pools)

            profiles = mikrotik_client.execute("/ip/hotspot/user/profile")
            assert any(p.get("name") == profile_name for p in profiles)

            users = mikrotik_client.execute("/ip/hotspot/user")
            user = next((u for u in users if u.get("name") == user_name), None)
            assert user is not None
            assert user.get("profile") == profile_name

            logger.info("  ✓ All configurations verified")

            # Step 5: Simulate user activity
            logger.info("Step 5: Simulating user lifecycle...")

            # Disable (simulate expiry)
            mikrotik_client.execute(
                "/ip/hotspot/user",
                method="set",
                id=user[".id"],
                disabled="yes"
            )
            logger.info("  ✓ User disabled (package expired)")

            # Re-enable (simulate renewal)
            mikrotik_client.execute(
                "/ip/hotspot/user",
                method="set",
                id=user[".id"],
                disabled="no",
                **{
                    "limit-bytes-total": "2147483648"  # Upgraded to 2GB
                }
            )
            logger.info("  ✓ User re-enabled (package renewed with 2GB)")

            logger.info("=" * 60)
            logger.info("INTEGRATION TEST PASSED: Hotspot Provisioning")
            logger.info("=" * 60)

        finally:
            # Cleanup
            logger.info("Cleaning up test resources...")

            try:
                users = mikrotik_client.execute("/ip/hotspot/user")
                user = next((u for u in users if u.get("name") == user_name), None)
                if user:
                    mikrotik_client.execute("/ip/hotspot/user", method="remove", id=user[".id"])
            except:
                pass

            try:
                profiles = mikrotik_client.execute("/ip/hotspot/user/profile")
                profile = next((p for p in profiles if p.get("name") == profile_name), None)
                if profile:
                    mikrotik_client.execute("/ip/hotspot/user/profile", method="remove", id=profile[".id"])
            except:
                pass

            try:
                pools = mikrotik_client.execute("/ip/pool")
                pool = next((p for p in pools if p.get("name") == pool_name), None)
                if pool:
                    mikrotik_client.execute("/ip/pool", method="remove", id=pool[".id"])
            except:
                pass

            logger.info("  ✓ Cleanup completed")

    def test_complete_pppoe_provisioning_flow(self, mikrotik_client, test_config):
        """Test complete PPPoE provisioning from scratch."""
        logger.info("=" * 60)
        logger.info("INTEGRATION TEST: Complete PPPoE Provisioning")
        logger.info("=" * 60)

        prefix = f"{test_config.test_prefix}pppoe_"
        pool_name = f"{prefix}pool"
        profile_name = f"{prefix}profile"
        user_name = f"{prefix}user"

        try:
            # Step 1: Create IP pool
            logger.info("Step 1: Creating IP pool...")
            mikrotik_client.execute(
                "/ip/pool",
                method="add",
                name=pool_name,
                ranges="172.33.1.100-172.33.1.200"
            )
            logger.info(f"  ✓ Created pool: {pool_name}")

            # Step 2: Create PPP profile with bandwidth
            logger.info("Step 2: Creating PPP profile...")
            mikrotik_client.execute(
                "/ppp/profile",
                method="add",
                name=profile_name,
                **{
                    "local-address": "172.33.1.1",
                    "remote-address": pool_name,
                    "rate-limit": "10M/5M",  # 10Mbps down / 5Mbps up
                    "only-one": "yes"  # Allow only one session per user
                }
            )
            logger.info(f"  ✓ Created profile: {profile_name} (10Mbps/5Mbps)")

            # Step 3: Create test user
            logger.info("Step 3: Creating PPPoE user...")
            mikrotik_client.execute(
                "/ppp/secret",
                method="add",
                name=user_name,
                password="testpass123",
                service="pppoe",
                profile=profile_name,
                comment=f"Test user created: {datetime.utcnow()}"
            )
            logger.info(f"  ✓ Created user: {user_name}")

            # Step 4: Verify configuration
            logger.info("Step 4: Verifying configuration...")

            pools = mikrotik_client.execute("/ip/pool")
            assert any(p.get("name") == pool_name for p in pools)

            profiles = mikrotik_client.execute("/ppp/profile")
            profile = next((p for p in profiles if p.get("name") == profile_name), None)
            assert profile is not None
            assert profile.get("rate-limit") == "10M/5M"

            users = mikrotik_client.execute("/ppp/secret")
            user = next((u for u in users if u.get("name") == user_name), None)
            assert user is not None
            assert user.get("profile") == profile_name

            logger.info("  ✓ All configurations verified")

            # Step 5: Simulate user lifecycle
            logger.info("Step 5: Simulating user lifecycle...")

            # Disable (simulate expiry)
            mikrotik_client.execute(
                "/ppp/secret",
                method="set",
                id=user[".id"],
                disabled="yes",
                comment=f"Expired: {datetime.utcnow()}"
            )
            logger.info("  ✓ User disabled (package expired)")

            # Re-enable (simulate renewal)
            mikrotik_client.execute(
                "/ppp/secret",
                method="set",
                id=user[".id"],
                disabled="no",
                comment=f"Renewed: {datetime.utcnow()}"
            )
            logger.info("  ✓ User re-enabled (package renewed)")

            # Upgrade profile
            upgraded_profile = f"{prefix}premium"
            mikrotik_client.execute(
                "/ppp/profile",
                method="add",
                name=upgraded_profile,
                **{
                    "local-address": "172.33.1.1",
                    "remote-address": pool_name,
                    "rate-limit": "20M/10M"  # Upgraded to 20Mbps/10Mbps
                }
            )

            mikrotik_client.execute(
                "/ppp/secret",
                method="set",
                id=user[".id"],
                profile=upgraded_profile,
                comment=f"Upgraded to premium: {datetime.utcnow()}"
            )
            logger.info("  ✓ User upgraded to premium profile (20Mbps/10Mbps)")

            logger.info("=" * 60)
            logger.info("INTEGRATION TEST PASSED: PPPoE Provisioning")
            logger.info("=" * 60)

        finally:
            # Cleanup
            logger.info("Cleaning up test resources...")

            try:
                users = mikrotik_client.execute("/ppp/secret")
                user = next((u for u in users if u.get("name") == user_name), None)
                if user:
                    mikrotik_client.execute("/ppp/secret", method="remove", id=user[".id"])
            except:
                pass

            try:
                profiles = mikrotik_client.execute("/ppp/profile")
                for p in profiles:
                    if p.get("name", "").startswith(prefix):
                        mikrotik_client.execute("/ppp/profile", method="remove", id=p[".id"])
            except:
                pass

            try:
                pools = mikrotik_client.execute("/ip/pool")
                pool = next((p for p in pools if p.get("name") == pool_name), None)
                if pool:
                    mikrotik_client.execute("/ip/pool", method="remove", id=pool[".id"])
            except:
                pass

            logger.info("  ✓ Cleanup completed")


class TestCleanup:
    """Cleanup tests to remove any leftover test data."""

    def test_cleanup_test_users(self, mikrotik_client, test_config):
        """Cleanup any test users left from previous runs."""
        logger.info("Cleaning up test users...")

        # Cleanup hotspot users
        hotspot_users = mikrotik_client.execute("/ip/hotspot/user")
        for user in hotspot_users:
            if user.get("name", "").startswith(test_config.test_prefix):
                try:
                    mikrotik_client.execute("/ip/hotspot/user", method="remove", id=user[".id"])
                    logger.info(f"  Removed hotspot user: {user.get('name')}")
                except:
                    pass

        # Cleanup PPPoE users
        pppoe_users = mikrotik_client.execute("/ppp/secret")
        for user in pppoe_users:
            if user.get("name", "").startswith(test_config.test_prefix):
                try:
                    mikrotik_client.execute("/ppp/secret", method="remove", id=user[".id"])
                    logger.info(f"  Removed PPPoE user: {user.get('name')}")
                except:
                    pass

        logger.info("✓ Test user cleanup completed")

    def test_cleanup_test_profiles(self, mikrotik_client, test_config):
        """Cleanup any test profiles left from previous runs."""
        logger.info("Cleaning up test profiles...")

        # Cleanup hotspot user profiles
        try:
            profiles = mikrotik_client.execute("/ip/hotspot/user/profile")
            for profile in profiles:
                if profile.get("name", "").startswith(test_config.test_prefix):
                    try:
                        mikrotik_client.execute("/ip/hotspot/user/profile", method="remove", id=profile[".id"])
                        logger.info(f"  Removed hotspot profile: {profile.get('name')}")
                    except:
                        pass
        except:
            pass

        # Cleanup PPP profiles
        try:
            profiles = mikrotik_client.execute("/ppp/profile")
            for profile in profiles:
                if profile.get("name", "").startswith(test_config.test_prefix):
                    try:
                        mikrotik_client.execute("/ppp/profile", method="remove", id=profile[".id"])
                        logger.info(f"  Removed PPP profile: {profile.get('name')}")
                    except:
                        pass
        except:
            pass

        logger.info("✓ Test profile cleanup completed")

    def test_cleanup_test_pools(self, mikrotik_client, test_config):
        """Cleanup any test IP pools left from previous runs."""
        logger.info("Cleaning up test IP pools...")

        try:
            pools = mikrotik_client.execute("/ip/pool")
            for pool in pools:
                if pool.get("name", "").startswith(test_config.test_prefix):
                    try:
                        mikrotik_client.execute("/ip/pool", method="remove", id=pool[".id"])
                        logger.info(f"  Removed IP pool: {pool.get('name')}")
                    except:
                        pass
        except:
            pass

        logger.info("✓ Test pool cleanup completed")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def run_tests():
    """Run tests programmatically."""
    import sys

    # Run pytest with verbose output
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))


if __name__ == "__main__":
    print("=" * 70)
    print("MikroTik Router Provisioning Test Suite")
    print("=" * 70)
    print(f"Target Router: 192.168.100.7:8728")
    print()
    print("This test suite validates:")
    print("  - Router connectivity and API access")
    print("  - Hotspot server configuration")
    print("  - PPPoE server configuration")
    print("  - User management (create, disable, enable, delete)")
    print("  - Bandwidth management (profiles, queues)")
    print("  - Package expiry workflows")
    print("  - Captive portal configuration")
    print()
    print("=" * 70)

    run_tests()
