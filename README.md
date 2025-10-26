# Codevertex ISP Billing System - Backend

A comprehensive, production-ready ISP billing and management system built with FastAPI, supporting MikroTik router integration, M-PESA payments, RBAC, and multi-tenant architecture.

## Features

### Core Features
- **RBAC System**: Role-Based Access Control with 4 roles (Superuser, Admin, Technician, Customer) and 70 granular permissions
- **User Management**: Complete user lifecycle management with multi-role authentication
- **MikroTik Integration**: RouterOS API integration for PPPoE, Hotspot, and device provisioning
- **Automated Provisioning**: 3-step wizard for router provisioning with live log streaming
- **Billing Engine**: Automated invoicing, usage tracking, and payment reconciliation
- **M-PESA Integration**: STK Push, C2B callbacks, and payment verification
- **SMS Credit Management**: Multi-provider SMS gateway with credit tracking
- **Real-time Monitoring**: Live router status, user activity, and system metrics
- **Background Tasks**: Celery-based task queue for billing, notifications, and maintenance
- **Advanced Analytics**: Comprehensive reporting with export functionality
- **Licence Management**: Trial periods, subscription tracking, and licence validation

## Tech Stack

- **Framework**: FastAPI 0.104+
- **Database**: PostgreSQL 15+
- **Cache/Queue**: Redis 7+
- **Background Jobs**: Celery 5+
- **ORM**: SQLAlchemy 2.0+
- **Authentication**: JWT with refresh tokens
- **Validation**: Pydantic V2
- **Testing**: Pytest with async support
- **Documentation**: OpenAPI/Swagger with ReDoc

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── core/                   # Core configuration and utilities
│   │   ├── __init__.py
│   │   ├── config.py          # Settings and configuration
│   │   ├── security.py        # JWT and password utilities
│   │   ├── database.py        # Database connection and session
│   │   └── logging.py         # Logging configuration
│   ├── models/                 # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── base.py            # Base model class
│   │   ├── user.py            # User and role models
│   │   ├── router.py          # Router and device models
│   │   ├── plan.py            # Service plans and packages
│   │   ├── subscription.py    # User subscriptions
│   │   ├── billing.py         # Invoices and payments
│   │   └── notification.py    # Notifications and tickets
│   ├── schemas/                # Pydantic schemas
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── router.py
│   │   ├── plan.py
│   │   ├── subscription.py
│   │   ├── billing.py
│   │   └── notification.py
│   ├── api/                    # API routes
│   │   ├── __init__.py
│   │   ├── deps.py            # Dependencies and middleware
│   │   └── v1/                # API version 1
│   │       ├── __init__.py
│   │       ├── auth.py
│   │       ├── users.py
│   │       ├── routers.py
│   │       ├── plans.py
│   │       ├── subscriptions.py
│   │       ├── billing.py
│   │       └── notifications.py
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── router_service.py
│   │   ├── billing_service.py
│   │   ├── mpesa_service.py
│   │   └── notification_service.py
│   ├── integrations/           # External service integrations
│   │   ├── __init__.py
│   │   ├── mikrotik.py        # MikroTik RouterOS API
│   │   ├── mpesa.py           # MPESA Daraja API
│   │   └── sms_email.py       # SMS and email services
│   ├── tasks/                  # Celery background tasks
│   │   ├── __init__.py
│   │   ├── billing_tasks.py
│   │   ├── notification_tasks.py
│   │   └── router_tasks.py
│   └── utils/                  # Utility functions
│       ├── __init__.py
│       ├── validators.py
│       ├── formatters.py
│       └── helpers.py
├── alembic/                    # Database migrations
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
├── tests/                      # Test suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_users.py
│   ├── test_routers.py
│   └── test_billing.py
├── scripts/                    # Utility scripts
│   ├── init_db.py
│   ├── create_admin.py
│   └── migrate_data.py
├── docker/                     # Docker configurations
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   └── nginx.conf
├── .env.example               # Environment variables template
├── .gitignore
├── pyproject.toml             # Project dependencies and configuration
├── requirements.txt           # Production dependencies
├── requirements-dev.txt       # Development dependencies
├── docker-compose.yml         # Development environment
├── docker-compose.prod.yml    # Production environment
└── README.md
```

## Quick Start

### Development Setup

1. **Clone and setup environment:**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements-dev.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your database and Redis credentials
   ```

3. **Setup database:**
   ```bash
   alembic upgrade head
   python scripts/init_db.py
   ```

4. **Run development server:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Run Celery worker:**
   ```bash
   celery -A app.tasks worker --loglevel=info
   ```

### Docker Setup

```bash
docker-compose up -d
```

## API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Environment Variables

See `.env.example` for all required environment variables.

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_auth.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

## 📚 Documentation

### Core Documentation
- **[Complete Setup Guide](./docs/SETUP_GUIDE.md)** - Detailed installation and configuration instructions
- **[API Documentation](./docs/API_DOCUMENTATION.md)** - Complete API reference and examples
- **[Implementation Guide](./docs/IMPLEMENTATION_GUIDE.md)** - Technical implementation details
- **[Project Summary](./docs/PROJECT_SUMMARY.md)** - High-level overview and architecture

### Feature-Specific Guides
- **[RBAC System Guide](./docs/RBAC_SYSTEM.md)** - Role-based access control documentation
- **[MikroTik Provisioning Guide](./docs/MIKROTIK_PROVISIONING_GUIDE.md)** - Complete technical provisioning guide (1,400+ lines)
- **[Auth Mapping Guide](./docs/AUTH_MAPPING.md)** - Frontend to backend authentication mapping
- **[Swagger Authentication Guide](./docs/swagger_authentication_guide.md)** - API authentication setup

### Additional Resources
- **[Bug Fixes Log](./docs/BUG_FIXES.md)** - Known issues and resolutions
- **[OpenAPI Spec](./docs/openapi.json)** - OpenAPI 3.0 specification
- **[Implementation Progress](../wifi-billing-software-frontend/docs/IMPLEMENTATION_PROGRESS.md)** - Feature completion status

## 🚀 Quick Links

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## 🔐 Default Credentials

After initial setup, use these credentials:

**Superuser Account** (Full system access):
- Username: `superuser`
- Password: `superuser123`

**Demo Admin Account** (ISP provider access):
- Username: `demo`
- Password: `demo123`

⚠️ **Important**: Change these passwords in production!

## 🛠️ Development Tools

- **Alembic**: Database migrations
- **Pytest**: Testing framework
- **Black**: Code formatting
- **Flake8**: Linting
- **MyPy**: Type checking
- **Pre-commit**: Git hooks

## 📊 Database Schema

The system uses PostgreSQL with the following main tables:
- `users` - User accounts and authentication
- `roles` & `permissions` - RBAC system
- `routers` - MikroTik devices
- `plans` - Service packages
- `subscriptions` - User subscriptions
- `invoices` & `payments` - Billing
- `licences` - Licence management
- `system_licences` - Trial licences

See [IMPLEMENTATION_GUIDE.md](./docs/IMPLEMENTATION_GUIDE.md) for complete schema documentation.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest tests/ -v`
5. Submit a pull request

## 📧 Support

For issues, questions, or contributions:
- **Email**: support@codevertexitsolutions.com
- **Documentation**: See `/docs` folder
- **GitHub Issues**: Create an issue in the repository

## 📝 License

MIT License - See LICENSE file for details

## 🏢 About Codevertex IT Solutions

Codevertex IT Solutions specializes in ISP management software, network automation, and billing systems.

---

**Version**: 1.0.0  
**Last Updated**: October 21, 2025  
**Status**: Production Ready ✅
