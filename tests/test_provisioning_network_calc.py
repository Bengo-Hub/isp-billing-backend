"""
Unit tests for network calculation functionality in provisioning service.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

class TestNetworkCalculation:
    """Test network calculation endpoint."""
    
    def test_network_calc_basic_subnet(self):
        """Test basic network calculation with standard subnet."""
        response = client.get("/api/v1/provisioning/network/calc?subnet=192.168.1.0&cidr=24")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["subnet_address"] == "192.168.1.0"
        assert data["cidr"] == 24
        assert data["gateway"] == "192.168.1.1"
        assert data["dhcp_pool_start"] == "192.168.1.100"
        assert data["dhcp_pool_end"] == "192.168.1.200"
        assert data["network_mask"] == "255.255.255.0"
        assert data["total_hosts"] == 254
        
    def test_network_calc_custom_subnet(self):
        """Test network calculation with custom subnet."""
        response = client.get("/api/v1/provisioning/network/calc?subnet=10.0.0.0&cidr=16")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["subnet_address"] == "10.0.0.0"
        assert data["cidr"] == 16
        assert data["gateway"] == "10.0.0.1"
        assert data["dhcp_pool_start"] == "10.0.100.0"
        assert data["dhcp_pool_end"] == "10.0.200.0"
        assert data["network_mask"] == "255.255.0.0"
        assert data["total_hosts"] == 65534
        
    def test_network_calc_small_subnet(self):
        """Test network calculation with small subnet (/28)."""
        response = client.get("/api/v1/provisioning/network/calc?subnet=172.16.1.0&cidr=28")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["subnet_address"] == "172.16.1.0"
        assert data["cidr"] == 28
        assert data["gateway"] == "172.16.1.1"
        assert data["dhcp_pool_start"] == "172.16.1.10"
        assert data["dhcp_pool_end"] == "172.16.1.13"
        assert data["network_mask"] == "255.255.255.240"
        assert data["total_hosts"] == 14
        
    def test_network_calc_missing_params(self):
        """Test network calculation with missing parameters."""
        response = client.get("/api/v1/provisioning/network/calc")
        
        assert response.status_code == 422  # Validation error
        
    def test_network_calc_invalid_subnet(self):
        """Test network calculation with invalid subnet."""
        response = client.get("/api/v1/provisioning/network/calc?subnet=invalid&cidr=24")
        
        assert response.status_code == 422  # Validation error
        
    def test_network_calc_invalid_cidr(self):
        """Test network calculation with invalid CIDR."""
        response = client.get("/api/v1/provisioning/network/calc?subnet=192.168.1.0&cidr=50")
        
        assert response.status_code == 422  # Validation error


class TestBootstrapCommandGeneration:
    """Test bootstrap command generation endpoint."""
    
    def test_bootstrap_command_generation(self):
        """Test bootstrap command generation."""
        response = client.get("/api/v1/provisioning/bootstrap/command")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "command" in data
        assert "script_url" in data
        assert "/tool fetch mode=https url=" in data["command"]
        assert "codevertex.rsc" in data["command"]
        assert "import codevertex.rsc" in data["command"]
        
    def test_bootstrap_script_generation(self):
        """Test bootstrap script generation."""
        response = client.get("/api/v1/provisioning/bootstrap/script")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "script" in data
        assert isinstance(data["script"], str)
        assert len(data["script"]) > 0


class TestProvisioningWorkflow:
    """Test provisioning workflow endpoints."""
    
    def test_start_provisioning_missing_data(self):
        """Test starting provisioning with missing data."""
        response = client.post("/api/v1/provisioning/workflow", json={})
        
        assert response.status_code == 422  # Validation error
        
    def test_provisioning_status_not_found(self):
        """Test getting status for non-existent session."""
        response = client.get("/api/v1/provisioning/sessions/999999/status")
        
        assert response.status_code == 404
