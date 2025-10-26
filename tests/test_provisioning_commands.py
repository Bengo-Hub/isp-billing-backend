"""
Unit tests for provisioning command generation and validation.
"""
import pytest
from unittest.mock import Mock, patch
from app.services.provisioning.commands import (
    _generate_configuration_commands,
    _generate_hotspot_commands,
    _generate_pppoe_commands,
    _load_command_templates
)

class TestCommandGeneration:
    """Test command generation functions."""
    
    def test_load_command_templates(self):
        """Test that command templates load correctly."""
        templates = _load_command_templates()
        
        assert "system" in templates
        assert "network" in templates
        assert "hotspot" in templates
        assert "pppoe" in templates
        assert "security" in templates
        
    def test_generate_configuration_commands_basic(self):
        """Test basic configuration command generation."""
        config = {
            "router_identity": "test-router",
            "bridge_ports": ["ether1", "ether2"],
            "enable_hotspot_anti_sharing": False,
            "custom_subnet": False
        }
        
        commands = _generate_configuration_commands(config)
        
        assert isinstance(commands, list)
        assert len(commands) > 0
        
        # Check that identity is set
        identity_commands = [cmd for cmd in commands if "identity" in cmd.lower()]
        assert len(identity_commands) > 0
        
        # Check that bridge is configured
        bridge_commands = [cmd for cmd in commands if "bridge" in cmd.lower()]
        assert len(bridge_commands) > 0
        
    def test_generate_configuration_commands_with_anti_sharing(self):
        """Test configuration with anti-sharing enabled."""
        config = {
            "router_identity": "test-router",
            "bridge_ports": ["ether1", "ether2"],
            "enable_hotspot_anti_sharing": True,
            "custom_subnet": False
        }
        
        commands = _generate_configuration_commands(config)
        
        # Check for anti-sharing rules
        anti_sharing_commands = [cmd for cmd in commands if "anti-sharing" in cmd.lower()]
        assert len(anti_sharing_commands) > 0
        
    def test_generate_configuration_commands_custom_subnet(self):
        """Test configuration with custom subnet."""
        config = {
            "router_identity": "test-router",
            "bridge_ports": ["ether1", "ether2"],
            "enable_hotspot_anti_sharing": False,
            "custom_subnet": True,
            "subnet_address": "192.168.100.0",
            "cidr": 24
        }
        
        commands = _generate_configuration_commands(config)
        
        # Check for custom IP configuration
        ip_commands = [cmd for cmd in commands if "192.168.100" in cmd]
        assert len(ip_commands) > 0
        
    def test_generate_hotspot_commands_basic(self):
        """Test basic hotspot command generation."""
        config = {
            "enable_hotspot": True,
            "hotspot_profile": "default",
            "dns_servers": ["8.8.8.8", "8.8.4.4"]
        }
        
        commands = _generate_hotspot_commands(config)
        
        assert isinstance(commands, list)
        assert len(commands) > 0
        
        # Check for hotspot configuration
        hotspot_commands = [cmd for cmd in commands if "hotspot" in cmd.lower()]
        assert len(hotspot_commands) > 0
        
        # Check for DNS configuration
        dns_commands = [cmd for cmd in commands if "8.8.8.8" in cmd]
        assert len(dns_commands) > 0
        
    def test_generate_pppoe_commands_basic(self):
        """Test basic PPPoE command generation."""
        config = {
            "enable_pppoe": True,
            "pppoe_profile": "default",
            "pppoe_pool": "pppoe-pool"
        }
        
        commands = _generate_pppoe_commands(config)
        
        assert isinstance(commands, list)
        assert len(commands) > 0
        
        # Check for PPPoE configuration
        pppoe_commands = [cmd for cmd in commands if "pppoe" in cmd.lower()]
        assert len(pppoe_commands) > 0
        
    def test_generate_commands_with_multiple_bridge_ports(self):
        """Test command generation with multiple bridge ports."""
        config = {
            "router_identity": "test-router",
            "bridge_ports": ["ether1", "ether2", "ether3", "ether4"],
            "enable_hotspot_anti_sharing": False,
            "custom_subnet": False
        }
        
        commands = _generate_configuration_commands(config)
        
        # Check that all bridge ports are included
        bridge_add_commands = [cmd for cmd in commands if "bridge port add" in cmd.lower()]
        assert len(bridge_add_commands) >= 4
        
        # Verify each port is mentioned
        for port in config["bridge_ports"]:
            port_commands = [cmd for cmd in commands if port in cmd]
            assert len(port_commands) > 0
            
    def test_command_validation(self):
        """Test that generated commands are valid RouterOS syntax."""
        config = {
            "router_identity": "test-router",
            "bridge_ports": ["ether1", "ether2"],
            "enable_hotspot_anti_sharing": True,
            "custom_subnet": True,
            "subnet_address": "192.168.50.0",
            "cidr": 24
        }
        
        commands = _generate_configuration_commands(config)
        
        # Check that commands don't contain invalid characters
        for command in commands:
            assert not command.startswith(" ")
            assert not command.endswith(" ")
            assert len(command.strip()) > 0
            
        # Check for proper RouterOS command structure
        identity_commands = [cmd for cmd in commands if cmd.startswith("/system identity")]
        assert len(identity_commands) > 0
        
        bridge_commands = [cmd for cmd in commands if cmd.startswith("/interface bridge")]
        assert len(bridge_commands) > 0


class TestCommandExecution:
    """Test command execution with retry logic."""
    
    @patch('app.services.provisioning.commands.RouterOSApi')
    def test_execute_command_with_retry_success(self, mock_api_class):
        """Test successful command execution."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        mock_api.execute_command.return_value = {"success": True}
        
        from app.services.provisioning.commands import _execute_command_with_retry
        
        result = _execute_command_with_retry(mock_api, "/test command", max_retries=3)
        
        assert result["success"] is True
        mock_api.execute_command.assert_called_once_with("/test command")
        
    @patch('app.services.provisioning.commands.RouterOSApi')
    def test_execute_command_with_retry_failure(self, mock_api_class):
        """Test command execution with retries."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        mock_api.execute_command.side_effect = Exception("Connection failed")
        
        from app.services.provisioning.commands import _execute_command_with_retry
        
        result = _execute_command_with_retry(mock_api, "/test command", max_retries=2)
        
        assert result["success"] is False
        assert "Connection failed" in result["error"]
        assert mock_api.execute_command.call_count == 2
