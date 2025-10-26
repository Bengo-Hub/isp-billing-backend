"""Test configuration and fixtures."""

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.config import settings
from app.main import app
from app.models.user import User, UserRole, UserStatus
from app.models.billing import Payment, PaymentStatus, PaymentMethod
from app.core.security import get_password_hash


# Test database URL
TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ispbilling_test"

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

# Create test session factory
TestSessionLocal = sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """Create a test database session."""
    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session
    async with TestSessionLocal() as session:
        yield session
    
    # Drop all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """Create a test client with database session override."""
    def override_get_db():
        return db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        username="testuser",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        hashed_password=get_password_hash("testpassword"),
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        is_verified=True,
        is_active=True,
    )
    
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    return user


@pytest_asyncio.fixture
async def test_admin_user(db_session: AsyncSession) -> User:
    """Create a test admin user."""
    admin = User(
        username="admin",
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        hashed_password=get_password_hash("adminpassword"),
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        is_verified=True,
        is_active=True,
    )
    
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    
    return admin


@pytest_asyncio.fixture
async def test_technician_user(db_session: AsyncSession) -> User:
    """Create a test technician user."""
    technician = User(
        username="technician",
        email="tech@example.com",
        first_name="Tech",
        last_name="User",
        hashed_password=get_password_hash("techpassword"),
        role=UserRole.TECHNICIAN,
        status=UserStatus.ACTIVE,
        is_verified=True,
        is_active=True,
    )
    
    db_session.add(technician)
    await db_session.commit()
    await db_session.refresh(technician)
    
    return technician


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_user: User):
    """Get authentication headers for test user."""
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": test_user.username, "password": "testpassword"}
    )
    
    assert response.status_code == 200
    token_data = response.json()
    
    return {"Authorization": f"Bearer {token_data['access_token']}"}


@pytest_asyncio.fixture
async def admin_auth_headers(client: AsyncClient, test_admin_user: User):
    """Get authentication headers for admin user."""
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": test_admin_user.username, "password": "adminpassword"}
    )
    
    assert response.status_code == 200
    token_data = response.json()
    
    return {"Authorization": f"Bearer {token_data['access_token']}"}


@pytest_asyncio.fixture
async def technician_auth_headers(client: AsyncClient, test_technician_user: User):
    """Get authentication headers for technician user."""
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": test_technician_user.username, "password": "techpassword"}
    )
    
    assert response.status_code == 200
    token_data = response.json()
    
    return {"Authorization": f"Bearer {token_data['access_token']}"}


@pytest_asyncio.fixture
async def test_user_with_phone(db_session: AsyncSession) -> User:
    """Create a test user with phone number for MPESA testing."""
    user = User(
        username="testuser_phone",
        email="testphone@example.com",
        first_name="Test",
        last_name="User",
        phone="+254712345678",
        hashed_password=get_password_hash("testpassword"),
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        is_verified=True,
        is_active=True,
    )
    
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    return user


@pytest_asyncio.fixture
async def test_payment(db_session: AsyncSession, test_user: User) -> Payment:
    """Create a test payment."""
    payment = Payment(
        user_id=test_user.id,
        amount=1000,
        currency="KES",
        payment_method=PaymentMethod.MPESA,
        status=PaymentStatus.PENDING,
        external_reference="test_checkout_id",
        description="Test Payment",
        metadata={"test": "data"}
    )
    
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)
    
    return payment


@pytest_asyncio.fixture
async def test_completed_payment(db_session: AsyncSession, test_user: User) -> Payment:
    """Create a test completed payment."""
    payment = Payment(
        user_id=test_user.id,
        amount=1000,
        currency="KES",
        payment_method=PaymentMethod.MPESA,
        status=PaymentStatus.COMPLETED,
        external_reference="test_transaction_id",
        description="Test Completed Payment",
        metadata={"test": "data"}
    )
    
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)
    
    return payment


@pytest_asyncio.fixture
def mock_mpesa_api():
    """Mock MPESA API for testing."""
    from unittest.mock import AsyncMock
    return AsyncMock()


@pytest_asyncio.fixture
def mock_mpesa_public_key():
    """Mock MPESA public key for testing."""
    from unittest.mock import MagicMock
    return MagicMock()


@pytest.fixture
def mpesa_callback_data():
    """Sample MPESA callback data for testing."""
    return {
        "signature": "test_signature",
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "test_merchant_id",
                "CheckoutRequestID": "test_checkout_id",
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": "1000"},
                        {"Name": "MpesaReceiptNumber", "Value": "test_receipt"},
                        {"Name": "TransactionDate", "Value": "20241201"},
                        {"Name": "PhoneNumber", "Value": "254712345678"}
                    ]
                }
            }
        }
    }


@pytest.fixture
def mpesa_failed_callback_data():
    """Sample MPESA failed callback data for testing."""
    return {
        "signature": "test_signature",
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "test_merchant_id",
                "CheckoutRequestID": "test_checkout_id",
                "ResultCode": 1,
                "ResultDesc": "The balance is insufficient for the transaction"
            }
        }
    }
