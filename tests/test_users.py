"""Test user management endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, UserStatus


class TestUserEndpoints:
    """Test user management endpoints."""

    async def test_get_current_user_profile(
        self, 
        client: AsyncClient, 
        auth_headers: dict, 
        test_user: User
    ):
        """Test getting current user profile."""
        response = await client.get("/api/v1/users/me", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id
        assert data["username"] == test_user.username
        assert data["email"] == test_user.email
        assert "subscription_count" in data
        assert "active_subscription_count" in data

    async def test_get_current_user_unauthorized(self, client: AsyncClient):
        """Test getting current user without authentication."""
        response = await client.get("/api/v1/users/me")
        
        assert response.status_code == 401

    async def test_update_current_user(
        self, 
        client: AsyncClient, 
        auth_headers: dict, 
        test_user: User
    ):
        """Test updating current user profile."""
        update_data = {
            "first_name": "Updated",
            "last_name": "Name",
            "phone": "+254712345678"
        }
        
        response = await client.patch(
            "/api/v1/users/me", 
            json=update_data, 
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Updated"
        assert data["last_name"] == "Name"
        assert data["phone"] == "+254712345678"

    async def test_update_current_user_unauthorized(self, client: AsyncClient):
        """Test updating current user without authentication."""
        update_data = {"first_name": "Updated"}
        
        response = await client.patch("/api/v1/users/me", json=update_data)
        
        assert response.status_code == 401

    async def test_get_all_users_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict
    ):
        """Test getting all users as admin."""
        response = await client.get("/api/v1/users/", headers=admin_auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "total" in data
        assert "page" in data
        assert "size" in data

    async def test_get_all_users_unauthorized(self, client: AsyncClient):
        """Test getting all users without authentication."""
        response = await client.get("/api/v1/users/")
        
        assert response.status_code == 401

    async def test_get_all_users_customer_forbidden(
        self, 
        client: AsyncClient, 
        auth_headers: dict
    ):
        """Test getting all users as customer (forbidden)."""
        response = await client.get("/api/v1/users/", headers=auth_headers)
        
        assert response.status_code == 403
        assert "Insufficient permissions" in response.json()["detail"]

    async def test_get_user_by_id_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict, 
        test_user: User
    ):
        """Test getting user by ID as admin."""
        response = await client.get(
            f"/api/v1/users/{test_user.id}", 
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id
        assert data["username"] == test_user.username

    async def test_get_user_by_id_technician(
        self, 
        client: AsyncClient, 
        technician_auth_headers: dict, 
        test_user: User
    ):
        """Test getting user by ID as technician."""
        response = await client.get(
            f"/api/v1/users/{test_user.id}", 
            headers=technician_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id

    async def test_get_user_by_id_customer_forbidden(
        self, 
        client: AsyncClient, 
        auth_headers: dict, 
        test_user: User
    ):
        """Test getting user by ID as customer (forbidden)."""
        response = await client.get(
            f"/api/v1/users/{test_user.id}", 
            headers=auth_headers
        )
        
        assert response.status_code == 403

    async def test_get_nonexistent_user(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict
    ):
        """Test getting nonexistent user."""
        response = await client.get("/api/v1/users/99999", headers=admin_auth_headers)
        
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]

    async def test_update_user_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict, 
        test_user: User
    ):
        """Test updating user as admin."""
        update_data = {
            "first_name": "Admin Updated",
            "last_name": "Name"
        }
        
        response = await client.patch(
            f"/api/v1/users/{test_user.id}", 
            json=update_data, 
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Admin Updated"
        assert data["last_name"] == "Name"

    async def test_update_user_unauthorized(
        self, 
        client: AsyncClient, 
        test_user: User
    ):
        """Test updating user without authentication."""
        update_data = {"first_name": "Updated"}
        
        response = await client.patch(
            f"/api/v1/users/{test_user.id}", 
            json=update_data
        )
        
        assert response.status_code == 401

    async def test_update_user_status_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict, 
        test_user: User
    ):
        """Test updating user status as admin."""
        response = await client.patch(
            f"/api/v1/users/{test_user.id}/status?status=suspended",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "suspended"

    async def test_update_user_role_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict, 
        test_user: User
    ):
        """Test updating user role as admin."""
        response = await client.patch(
            f"/api/v1/users/{test_user.id}/role?role=technician",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "technician"

    async def test_activate_user_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict, 
        test_user: User
    ):
        """Test activating user as admin."""
        # First suspend the user
        await client.patch(
            f"/api/v1/users/{test_user.id}/status?status=suspended",
            headers=admin_auth_headers
        )
        
        # Then activate
        response = await client.patch(
            f"/api/v1/users/{test_user.id}/activate",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"

    async def test_deactivate_user_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict, 
        test_user: User
    ):
        """Test deactivating user as admin."""
        response = await client.patch(
            f"/api/v1/users/{test_user.id}/deactivate",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False
        assert data["status"] == "inactive"

    async def test_delete_user_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict, 
        test_user: User
    ):
        """Test deleting user as admin."""
        response = await client.delete(
            f"/api/v1/users/{test_user.id}",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        assert "User deleted successfully" in response.json()["message"]

    async def test_delete_nonexistent_user(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict
    ):
        """Test deleting nonexistent user."""
        response = await client.delete(
            "/api/v1/users/99999",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]

    async def test_get_users_with_filters(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict
    ):
        """Test getting users with filters."""
        # Test role filter
        response = await client.get(
            "/api/v1/users/?role=customer",
            headers=admin_auth_headers
        )
        assert response.status_code == 200
        
        # Test status filter
        response = await client.get(
            "/api/v1/users/?status=active",
            headers=admin_auth_headers
        )
        assert response.status_code == 200
        
        # Test search filter
        response = await client.get(
            "/api/v1/users/?search=test",
            headers=admin_auth_headers
        )
        assert response.status_code == 200

    async def test_pagination(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict
    ):
        """Test pagination parameters."""
        response = await client.get(
            "/api/v1/users/?page=1&size=10",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["size"] == 10
