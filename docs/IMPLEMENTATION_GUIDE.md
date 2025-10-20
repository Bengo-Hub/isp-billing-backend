# ISP Billing System - Backend Implementation Guide

## 🎯 Project Overview

This is a comprehensive ISP billing system backend built with FastAPI, designed to manage MikroTik routers, handle billing, and integrate with MPESA payments. The system supports both Hotspot and PPPoE user management with a multi-tenant architecture.

## 🏗️ Architecture Highlights

### Modern FastAPI Best Practices
- **Async/Await**: Full async support throughout the application
- **Pydantic V2**: Latest validation and serialization
- **SQLAlchemy 2.0**: Modern ORM with async support
- **Type Hints**: Comprehensive type annotations
- **Dependency Injection**: Clean separation of concerns
- **Role-Based Access Control**: Multi-level permission system

### Database Design
- **PostgreSQL**: Primary database with proper indexing
- **Alembic**: Database migrations and version control
- **Async Sessions**: Non-blocking database operations
- **Proper Relationships**: Well-defined foreign keys and constraints

### Security Features
- **JWT Authentication**: Access and refresh tokens
- **Password Hashing**: Bcrypt with configurable rounds
- **Role-Based Permissions**: Admin, Technician, Customer roles
- **Session Management**: Track and revoke user sessions
- **Input Validation**: Comprehensive request validation

## 📁 Project Structure

```
backend/
├── app/                          # Main application package
│   ├── core/                     # Core configuration and utilities
│   │   ├── config.py            # Settings and environment variables
│   │   ├── security.py          # JWT and password utilities
│   │   ├── database.py          # Database connection and session
│   │   └── logging.py           # Logging configuration
│   ├── models/                   # SQLAlchemy database models
│   │   ├── base.py              # Base model with common fields
│   │   ├── user.py              # User and authentication models
│   │   ├── router.py            # Router and device models
│   │   ├── plan.py              # Service plans and packages
│   │   ├── subscription.py      # User subscriptions
│   │   ├── billing.py           # Invoices and payments
│   │   └── notification.py      # Notifications and tickets
│   ├── schemas/                  # Pydantic schemas for validation
│   │   └── user.py              # User-related schemas
│   ├── api/                      # API routes and dependencies
│   │   ├── deps.py              # Dependencies and middleware
│   │   └── v1/                  # API version 1
│   │       ├── auth.py          # Authentication endpoints
│   │       ├── users.py         # User management endpoints
│   │       ├── routers.py       # Router management endpoints
│   │       ├── plans.py         # Service plan endpoints
│   │       ├── subscriptions.py # Subscription endpoints
│   │       ├── billing.py       # Billing and payment endpoints
│   │       └── notifications.py # Notification endpoints
│   ├── services/                 # Business logic layer
│   │   ├── auth_service.py      # Authentication business logic
│   │   ├── user_service.py      # User management logic
│   │   └── notification_service.py # Notification logic
│   ├── integrations/             # External service integrations
│   │   ├── mikrotik.py          # MikroTik RouterOS API
│   │   ├── mpesa.py             # MPESA Daraja API
│   │   └── sms_email.py         # SMS and email services
│   ├── tasks/                    # Celery background tasks
│   │   ├── billing_tasks.py     # Billing automation tasks
│   │   ├── notification_tasks.py # Notification tasks
│   │   └── router_tasks.py      # Router management tasks
│   ├── utils/                    # Utility functions
│   │   ├── validators.py        # Custom validators
│   │   ├── formatters.py        # Data formatters
│   │   └── helpers.py           # Helper functions
│   └── main.py                  # FastAPI application entry point
├── alembic/                      # Database migrations
│   ├── versions/                # Migration files
│   ├── env.py                   # Alembic environment
│   └── script.py.mako           # Migration template
├── docker/                       # Docker configurations
│   ├── Dockerfile               # Production Docker image
│   └── Dockerfile.dev           # Development Docker image
├── scripts/                      # Utility scripts
│   ├── setup.sh                 # Linux/Mac setup script
│   ├── setup.bat                # Windows setup script
│   ├── init_db.py               # Database initialization
│   └── create_admin.py          # Admin user creation
├── tests/                        # Test suite
│   ├── conftest.py              # Test configuration
│   ├── test_auth.py             # Authentication tests
│   ├── test_users.py            # User management tests
│   └── test_billing.py          # Billing tests
├── pyproject.toml               # Project configuration
├── requirements.txt             # Production dependencies
├── requirements-dev.txt         # Development dependencies
├── docker-compose.yml           # Development environment
├── alembic.ini                  # Alembic configuration
├── env.example                  # Environment variables template
└── README.md                    # Project documentation
```

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL 15+
- Redis 7+
- Docker (optional)

### Development Setup

#### Option 1: Local Development
```bash
# Clone and navigate to backend directory
cd backend

# Run setup script
# Linux/Mac:
./scripts/setup.sh

# Windows:
scripts\setup.bat

# Or manual setup:
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp env.example .env
# Edit .env with your configuration
python scripts/init_db.py
python scripts/create_admin.py

# Start development server
uvicorn app.main:app --reload
```

#### Option 2: Docker Development
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend

# Stop services
docker-compose down
```

### Production Deployment
```bash
# Build production image
docker build -f docker/Dockerfile -t ispbilling-backend .

# Run with production settings
docker run -d \
  --name ispbilling-backend \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  -e REDIS_URL=redis://host:6379/0 \
  ispbilling-backend
```

## 🔧 Configuration

### Environment Variables
Copy `env.example` to `.env` and configure:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/ispbilling_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=your-super-secret-key-change-in-production

# MPESA (for production)
MPESA_CONSUMER_KEY=your-consumer-key
MPESA_CONSUMER_SECRET=your-consumer-secret
MPESA_PASSKEY=your-passkey
MPESA_SHORTCODE=your-shortcode
```

### Database Migrations
```bash
# Create new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

## 📚 API Documentation

### Authentication
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - Login and get tokens
- `POST /api/v1/auth/refresh` - Refresh access token
- `POST /api/v1/auth/logout` - Logout user
- `GET /api/v1/auth/me` - Get current user info

### User Management
- `GET /api/v1/users/` - List all users (admin)
- `GET /api/v1/users/me` - Get current user profile
- `PATCH /api/v1/users/me` - Update current user
- `PATCH /api/v1/users/{id}/status` - Update user status (admin)

### Service Plans
- `GET /api/v1/plans/` - List service plans
- `POST /api/v1/plans/` - Create plan (admin)
- `GET /api/v1/plans/{id}` - Get plan details
- `PATCH /api/v1/plans/{id}` - Update plan (admin)

### Billing
- `GET /api/v1/billing/invoices` - List invoices
- `POST /api/v1/billing/payments/mpesa/stk` - Initiate MPESA payment
- `POST /api/v1/billing/payments/mpesa/callback` - MPESA webhook

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth.py -v
```

## 🔒 Security Features

### Authentication & Authorization
- JWT-based authentication with access/refresh tokens
- Role-based access control (Admin, Technician, Customer)
- Session management with revocation capabilities
- Password hashing with bcrypt

### Input Validation
- Pydantic schemas for request/response validation
- Email and phone number validation
- SQL injection prevention through ORM
- XSS protection through proper escaping

### Rate Limiting
- Configurable rate limiting per endpoint
- IP-based and user-based limits
- Redis-backed rate limiting

## 🚧 Implementation Status

### ✅ Completed
- [x] Project structure and configuration
- [x] Database models and relationships
- [x] Authentication and authorization system
- [x] User management API
- [x] Basic API structure for all modules
- [x] Docker configuration
- [x] Database migrations setup
- [x] Development environment setup

### 🚧 In Progress
- [ ] MikroTik router integration
- [ ] MPESA payment integration
- [ ] Celery background tasks
- [ ] Comprehensive test suite
- [ ] Production deployment configuration

### 📋 Next Steps
1. **MikroTik Integration**: Implement RouterOS API integration
2. **MPESA Integration**: Add Daraja API integration
3. **Background Tasks**: Implement Celery tasks for billing
4. **Testing**: Add comprehensive test coverage
5. **Monitoring**: Add logging and monitoring
6. **Documentation**: Complete API documentation

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue in the repository
- Check the documentation
- Review the API documentation at `/docs`

---

**Note**: This is a development version. For production deployment, ensure all security configurations are properly set and all environment variables are configured correctly.
