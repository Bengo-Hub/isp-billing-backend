# MPESA Integration Tests

This directory contains comprehensive tests for the MPESA Daraja API integration in the ISP Billing System.

## Test Structure

### Test Files

- **`test_mpesa_integration.py`** - Tests for the core MPESA API integration class
- **`test_mpesa_service.py`** - Tests for the high-level MPESA service
- **`test_mpesa_api.py`** - Tests for MPESA REST API endpoints
- **`test_mpesa_schemas.py`** - Tests for MPESA Pydantic schemas
- **`conftest.py`** - Test configuration and fixtures
- **`test_runner.py`** - Test runner script with various options

### Test Categories

#### 1. Unit Tests
- Individual component testing
- Mock external dependencies
- Fast execution
- Isolated testing

#### 2. Integration Tests
- Component interaction testing
- Database integration
- API endpoint testing
- End-to-end workflows

#### 3. MPESA-Specific Tests
- STK Push functionality
- Callback processing
- Signature verification
- Error handling

## Running Tests

### Prerequisites

1. **Database Setup**
   ```bash
   # Create test database
   createdb ispbilling_test
   
   # Set environment variables
   export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ispbilling_test"
   export REDIS_URL="redis://localhost:6379/1"
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements-dev.txt
   ```

### Running All Tests

```bash
# Run all MPESA tests
python tests/test_runner.py

# Run with coverage
python tests/test_runner.py --coverage

# Run specific test file
python tests/test_runner.py --test test_mpesa_integration.py
```

### Using pytest directly

```bash
# Run all tests
pytest

# Run MPESA tests only
pytest -m mpesa

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_mpesa_integration.py

# Run with coverage
pytest --cov=app.integrations.mpesa --cov-report=html
```

## Test Configuration

### Environment Variables

The tests use the following environment variables:

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ispbilling_test

# Redis
REDIS_URL=redis://localhost:6379/1

# MPESA Configuration
MPESA_ENVIRONMENT=sandbox
MPESA_CONSUMER_KEY=test_key
MPESA_CONSUMER_SECRET=test_secret
MPESA_PASSKEY=test_passkey
MPESA_SHORTCODE=123456
MPESA_CALLBACK_URL=https://example.com/callback

# Testing
TESTING=true
```

### Fixtures

The test suite includes several fixtures for common test scenarios:

- **`test_user`** - Basic test user
- **`test_user_with_phone`** - User with phone number for MPESA
- **`test_admin_user`** - Admin user for privileged operations
- **`test_payment`** - Sample payment record
- **`test_completed_payment`** - Completed payment for reversal tests
- **`mpesa_callback_data`** - Sample successful callback data
- **`mpesa_failed_callback_data`** - Sample failed callback data

## Test Coverage

### Core Components

1. **MpesaAPI Class**
   - Credential validation
   - Access token management
   - STK Push initiation
   - Status queries
   - Callback processing
   - Signature verification
   - Error handling

2. **MpesaService Class**
   - Payment initiation
   - Status queries
   - Callback processing
   - Transaction reversals
   - Statistics generation
   - Database integration

3. **API Endpoints**
   - Authentication requirements
   - Input validation
   - Error responses
   - Response formatting
   - HTTP status codes

4. **Pydantic Schemas**
   - Data validation
   - Type checking
   - Field constraints
   - Error handling

### Test Scenarios

#### Happy Path Tests
- Successful payment initiation
- Successful status queries
- Successful callback processing
- Successful reversals

#### Error Handling Tests
- Invalid credentials
- Network failures
- Validation errors
- Database errors
- API errors

#### Edge Cases
- Missing phone numbers
- Invalid amounts
- Malformed callbacks
- Signature verification failures
- Timeout scenarios

## Mocking Strategy

### External Dependencies

1. **MPESA API Calls**
   - Mocked using `unittest.mock.AsyncMock`
   - Simulated responses for different scenarios
   - Error simulation for failure testing

2. **Database Operations**
   - Test database with isolated transactions
   - Fixtures for common data scenarios
   - Rollback after each test

3. **File System**
   - Mocked public key loading
   - Simulated file operations
   - Error condition testing

### Mock Examples

```python
# Mock MPESA API response
mock_response = {
    "success": True,
    "data": {
        "CheckoutRequestID": "test_checkout_id",
        "MerchantRequestID": "test_merchant_id"
    }
}

with patch.object(mpesa_api, 'stk_push', return_value=mock_response):
    result = await mpesa_service.initiate_payment(...)
```

## Continuous Integration

### GitHub Actions

The tests are designed to run in CI/CD pipelines:

```yaml
name: MPESA Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:13
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:6
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      - name: Run tests
        run: |
          python tests/test_runner.py --coverage
```

## Debugging Tests

### Verbose Output

```bash
# Run with maximum verbosity
pytest -vvv --tb=long

# Show print statements
pytest -s

# Run specific test with debugging
pytest -vvv tests/test_mpesa_integration.py::TestMpesaAPI::test_stk_push_success
```

### Test Database

```bash
# Connect to test database
psql postgresql://postgres:postgres@localhost:5432/ispbilling_test

# Check test data
SELECT * FROM payments WHERE payment_method = 'MPESA';
```

### Logging

Tests include comprehensive logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Performance Testing

### Load Testing

For performance testing of MPESA integration:

```python
import asyncio
import time

async def load_test_payments():
    """Test payment initiation under load."""
    start_time = time.time()
    
    tasks = []
    for i in range(100):
        task = mpesa_service.initiate_payment(...)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    
    end_time = time.time()
    print(f"Processed 100 payments in {end_time - start_time:.2f} seconds")
```

## Security Testing

### Signature Verification

Tests include security-focused scenarios:

- Invalid signature handling
- Malformed callback data
- Signature bypass attempts
- Public key validation

### Input Validation

- SQL injection prevention
- XSS protection
- Input sanitization
- Type validation

## Best Practices

### Test Organization

1. **Arrange-Act-Assert Pattern**
   ```python
   def test_payment_initiation():
       # Arrange
       user = create_test_user()
       amount = 1000
       
       # Act
       result = await mpesa_service.initiate_payment(user, amount)
       
       # Assert
       assert result["success"] is True
   ```

2. **Descriptive Test Names**
   - `test_stk_push_success`
   - `test_callback_processing_with_invalid_signature`
   - `test_payment_reversal_when_payment_not_found`

3. **Isolated Tests**
   - Each test is independent
   - No shared state between tests
   - Cleanup after each test

### Error Testing

1. **Exception Testing**
   ```python
   with pytest.raises(ValidationError, match="Phone number is required"):
       await mpesa_service.initiate_payment(user_without_phone, 1000)
   ```

2. **Error Response Testing**
   ```python
   response = client.post("/api/v1/mpesa/initiate-payment", json=invalid_data)
   assert response.status_code == 400
   assert "validation error" in response.json()["detail"]
   ```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Check PostgreSQL is running
   - Verify database exists
   - Check connection string

2. **Import Errors**
   - Ensure backend directory is in Python path
   - Check virtual environment activation
   - Verify all dependencies installed

3. **Test Failures**
   - Check test database state
   - Verify mock configurations
   - Review test logs

### Debug Commands

```bash
# Check test database
psql -d ispbilling_test -c "SELECT COUNT(*) FROM payments;"

# Run single test with debugging
pytest -vvv -s tests/test_mpesa_integration.py::TestMpesaAPI::test_stk_push_success

# Check test coverage
pytest --cov=app.integrations.mpesa --cov-report=html
open htmlcov/index.html
```

## Contributing

When adding new tests:

1. Follow existing naming conventions
2. Include both positive and negative test cases
3. Add appropriate fixtures if needed
4. Update this documentation
5. Ensure tests are isolated and repeatable

## References

- [Safaricom Developer Portal](https://developer.safaricom.co.ke/)
- [MPESA Daraja API Documentation](https://developer.safaricom.co.ke/Documentation)
- [pytest Documentation](https://docs.pytest.org/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
