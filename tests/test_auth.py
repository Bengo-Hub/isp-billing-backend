"""Test authentication endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, UserStatus


class TestAuthEndpoints:
    """Test authentication endpoints."""

    async def test_register_user(self, client: AsyncClient, db_session: AsyncSession):
        """Test user registration."""
        user_data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": "newpassword123",
            "role": "customer"
        }
        
        response = await client.post("/api/v1/auth/register", json=user_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "newuser@example.com"
        assert data["role"] == "customer"
        assert "id" in data

    async def test_register_duplicate_username(self, client: AsyncClient, test_user: User):
        """Test registration with duplicate username."""
        user_data = {
            "username": test_user.username,
            "email": "different@example.com",
            "first_name": "Different",
            "last_name": "User",
            "password": "password123",
            "role": "customer"
        }
        
        response = await client.post("/api/v1/auth/register", json=user_data)
        
        assert response.status_code == 400
        assert "username already registered" in response.json()["detail"]

    async def test_register_duplicate_email(self, client: AsyncClient, test_user: User):
        """Test registration with duplicate email."""
        user_data = {
            "username": "differentuser",
            "email": test_user.email,
            "first_name": "Different",
            "last_name": "User",
            "password": "password123",
            "role": "customer"
        }
        
        response = await client.post("/api/v1/auth/register", json=user_data)
        
        assert response.status_code == 400
        assert "email already registered" in response.json()["detail"]

    async def test_login_success(self, client: AsyncClient, test_user: User):
        """Test successful login."""
        login_data = {
            "username": test_user.username,
            "password": "testpassword"
        }
        
        response = await client.post("/api/v1/auth/login", data=login_data)
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_invalid_credentials(self, client: AsyncClient):
        """Test login with invalid credentials."""
        login_data = {
            "username": "nonexistent",
            "password": "wrongpassword"
        }
        
        response = await client.post("/api/v1/auth/login", data=login_data)
        
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["detail"]

    async def test_login_inactive_user(self, client: AsyncClient, db_session: AsyncSession):
        """Test login with inactive user."""
        # Create inactive user
        inactive_user = User(
            username="inactive",
            email="inactive@example.com",
            first_name="Inactive",
            last_name="User",
            hashed_password="$2b$12$test",  # Hashed password
            role=UserRole.CUSTOMER,
            status=UserStatus.INACTIVE,
            is_active=False,
        )
        db_session.add(inactive_user)
        await db_session.commit()
        
        login_data = {
            "username": "inactive",
            "password": "testpassword"
        }
        
        response = await client.post("/api/v1/auth/login", data=login_data)
        
        assert response.status_code == 400
        assert "Inactive user" in response.json()["detail"]

    async def test_get_current_user(self, client: AsyncClient, auth_headers: dict, test_user: User):
        """Test getting current user info."""
        response = await client.get("/api/v1/auth/me", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id
        assert data["username"] == test_user.username
        assert data["email"] == test_user.email

    async def test_get_current_user_unauthorized(self, client: AsyncClient):
        """Test getting current user without authentication."""
        response = await client.get("/api/v1/auth/me")
        
        assert response.status_code == 401

    async def test_refresh_token(self, client: AsyncClient, test_user: User):
        """Test token refresh."""
        # First login to get tokens
        login_data = {
            "username": test_user.username,
            "password": "testpassword"
        }
        
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        refresh_token = login_response.json()["refresh_token"]
        
        # Refresh token
        refresh_data = {"refresh_token": refresh_token}
        response = await client.post("/api/v1/auth/refresh", json=refresh_data)
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_invalid_token(self, client: AsyncClient):
        """Test refresh with invalid token."""
        refresh_data = {"refresh_token": "invalid_token"}
        response = await client.post("/api/v1/auth/refresh", json=refresh_data)
        
        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["detail"]

    async def test_logout(self, client: AsyncClient, auth_headers: dict):
        """Test user logout."""
        response = await client.post("/api/v1/auth/logout", headers=auth_headers)
        
        assert response.status_code == 200
        assert "Successfully logged out" in response.json()["message"]

    async def test_change_password(self, client: AsyncClient, auth_headers: dict, test_user: User):
        """Test password change."""
        password_data = {
            "current_password": "testpassword",
            "new_password": "newpassword123"
        }
        
        response = await client.post(
            "/api/v1/auth/change-password", 
            json=password_data, 
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert "Password changed successfully" in response.json()["message"]

    async def test_change_password_wrong_current(self, client: AsyncClient, auth_headers: dict):
        """Test password change with wrong current password."""
        password_data = {
            "current_password": "wrongpassword",
            "new_password": "newpassword123"
        }
        
        response = await client.post(
            "/api/v1/auth/change-password", 
            json=password_data, 
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert "Current password is incorrect" in response.json()["detail"]

    async def test_forgot_password(self, client: AsyncClient, test_user: User):
        """Test forgot password request."""
        forgot_data = {"email": test_user.email}
        
        response = await client.post("/api/v1/auth/forgot-password", json=forgot_data)
        
        assert response.status_code == 200
        assert "Password reset instructions sent" in response.json()["message"]

    async def test_forgot_password_nonexistent_email(self, client: AsyncClient):
        """Test forgot password with nonexistent email."""
        forgot_data = {"email": "nonexistent@example.com"}
        
        response = await client.post("/api/v1/auth/forgot-password", json=forgot_data)
        
        # Should still return 200 to avoid revealing if email exists
        assert response.status_code == 200
        assert "Password reset instructions sent" in response.json()["message"]
