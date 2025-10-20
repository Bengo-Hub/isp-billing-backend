# ISP Billing System - Backend

A comprehensive ISP billing system built with FastAPI, supporting MikroTik router integration, MPESA payments, and multi-tenant architecture.

## Features

- **User Management**: Multi-role authentication (Admin, Technician, Customer)
- **Router Integration**: MikroTik RouterOS API integration for PPPoE and Hotspot
- **Billing Engine**: Automated invoicing with usage tracking
- **Payment Integration**: MPESA STK Push and C2B callbacks
- **Real-time Monitoring**: Router status and user activity tracking
- **Background Tasks**: Celery-based task queue for billing and notifications

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
pytest tests/ -v
```

## License

MIT License
