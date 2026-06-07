# ISP Billing Software - Complete Setup Guide

## Table of Contents
1. [Quick Start (One-Command Setup)](#quick-start-one-command-setup)
2. [Prerequisites](#prerequisites)
3. [Environment Setup](#environment-setup)
4. [Database Configuration](#database-configuration)
5. [Backend Setup](#backend-setup)
6. [Frontend Setup](#frontend-setup)
7. [Initial Configuration](#initial-configuration)
8. [Running the Application](#running-the-application)
9. [Verification](#verification)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start (One-Command Setup)

### 🚀 Fastest Way to Get Started

For the quickest setup experience, use our all-in-one setup script:

```bash
# Navigate to backend directory
cd wifi-billing-software-backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate  # Linux/MacOS
# OR
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp env.example .env

# Edit .env with your PostgreSQL credentials
nano .env  # or use your preferred editor

# Run complete setup script
python scripts/setup_complete.py
```

**What this script does**:
1. ✅ Runs all database migrations (Alembic)
2. ✅ Cleans expired sessions and old data
3. ✅ Initializes RBAC system (4 roles, 70 permissions)
4. ✅ Creates **superuser** account (`superuser` / `superuser123`)
5. ✅ Creates **demo admin** account (`demo` / `demo123`)
6. ✅ Assigns RBAC roles to admin users
7. ✅ Creates 14-day trial licence
8. ✅ Seeds sample data (plans, users, routers)
9. ✅ Verifies setup completion

**Then start the server**:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Access the application**:
- **Backend API**: http://localhost:8000
- **Swagger Docs**: http://localhost:8000/docs
- **Login with**: `demo` / `demo123`

### Script Options

```bash
# Skip sample data (only create essentials)
python scripts/setup_complete.py --skip-sample-data

# Fresh install (⚠️ DANGER: Deletes all data!)
python scripts/setup_complete.py --fresh-install
```

---

## Prerequisites

### Required Software
Before starting, ensure you have the following installed:

#### 1. **Python 3.11 or higher**
```bash
# Check Python version
python --version
# or
python3 --version
```
Download from: https://www.python.org/downloads/

#### 2. **Node.js 18.x or higher**
```bash
# Check Node.js version
node --version

# Check npm version
npm --version
```
Download from: https://nodejs.org/

#### 3. **PostgreSQL 14 or higher**
```bash
# Check PostgreSQL version
psql --version
```
Download from: https://www.postgresql.org/download/

#### 4. **Redis (Optional - for background tasks)**
```bash
# Check Redis version
redis-cli --version
```
Download from: https://redis.io/download

#### 5. **Git**
```bash
# Check Git version
git --version
```
Download from: https://git-scm.com/downloads

---

## Environment Setup

### 1. Clone the Repository
```bash
# Clone the project
git clone <repository-url>
cd ISPBilling

# Verify structure
ls -la
# You should see: wifi-billing-software-backend/ and wifi-billing-software-frontend/
```

### 2. Backend Environment Setup

#### Step 1: Navigate to Backend Directory
```bash
cd wifi-billing-software-backend
```

#### Step 2: Create Python Virtual Environment
**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/MacOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

#### Step 3: Upgrade pip
```bash
python -m pip install --upgrade pip
```

#### Step 4: Install Python Dependencies
```bash
# Install all required packages
pip install -r requirements.txt

# For development (includes testing tools)
pip install -r requirements-dev.txt
```

### 3. Frontend Environment Setup

#### Step 1: Navigate to Frontend Directory
```bash
cd ../wifi-billing-software-frontend
```

#### Step 2: Install Node Dependencies
```bash
# Install all npm packages
npm install

# Or use yarn
yarn install
```

---

## Database Configuration

### 1. Create PostgreSQL Database

#### Step 1: Access PostgreSQL
```bash
# Linux/MacOS
sudo -u postgres psql

# Windows (from PostgreSQL bin directory)
psql -U postgres
```

#### Step 2: Create Database and User
```sql
-- Create database
CREATE DATABASE isp_billing;

-- Create user with password
CREATE USER isp_admin WITH PASSWORD 'your_secure_password';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE isp_billing TO isp_admin;

-- Grant schema privileges
\c isp_billing
GRANT ALL ON SCHEMA public TO isp_admin;

-- Exit psql
\q
```

#### Step 3: Verify Database Connection
```bash
psql -U isp_admin -d isp_billing -h localhost
```

### 2. Redis Setup (Optional)

#### Install and Start Redis

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

**MacOS:**
```bash
brew install redis
brew services start redis
```

**Windows:**
Use Docker:
```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

#### Verify Redis
```bash
redis-cli ping
# Should return: PONG
```

---

## Backend Setup

### 1. Configure Environment Variables

#### Step 1: Copy Environment Template
```bash
cd wifi-billing-software-backend
cp env.example .env
```

#### Step 2: Edit `.env` File
```bash
# Open with your preferred editor
nano .env
# or
code .env
```

#### Step 3: Configure Required Variables
```ini
# Application Settings
APP_NAME="Codevertex ISP Billing"
APP_ENV=development
DEBUG=true
API_VERSION=v1

# Server Settings
HOST=0.0.0.0
PORT=8000
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000

# Database Configuration
DATABASE_URL=postgresql://isp_admin:your_secure_password@localhost:5432/isp_billing
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Security Settings
SECRET_KEY=your-super-secret-key-change-this-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS Settings
CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"]

# Redis Configuration (Optional)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Celery Configuration (Optional)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Email Configuration (Optional - for notifications)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-specific-password
SMTP_FROM=noreply@codevertexitsolutions.com

# M-Pesa Configuration (Optional - for payments)
MPESA_ENVIRONMENT=sandbox
MPESA_CONSUMER_KEY=your-consumer-key
MPESA_CONSUMER_SECRET=your-consumer-secret
MPESA_SHORTCODE=174379
MPESA_PASSKEY=your-passkey
MPESA_CALLBACK_URL=https://yourdomain.com/api/v1/mpesa/callback

# SMS Gateway Configuration (Optional)
SMS_PROVIDER=africastalking
SMS_API_KEY=your-api-key
SMS_USERNAME=your-username
SMS_SENDER_ID=CODEVERTEX

# MikroTik Configuration
MIKROTIK_DEFAULT_PORT=8728
MIKROTIK_API_TIMEOUT=30

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
```

### 2. Initialize Database

#### ⭐ Recommended: One-Command Setup (All-in-One)
```bash
# Ensure you're in the backend directory and venv is activated
cd wifi-billing-software-backend
source venv/bin/activate  # Linux/MacOS
# or
venv\Scripts\activate  # Windows

# Run complete setup (migrations + RBAC + admin accounts + demo licence)
python scripts/setup_complete.py
```

**What this script does**:
1. ✅ Runs all database migrations
2. ✅ Cleans old/invalid data
3. ✅ Initializes RBAC system (roles and permissions)
4. ✅ Creates superuser account (`superuser` / `superuser123`)
5. ✅ Creates demo admin account (`demo` / `demo123`)
6. ✅ Assigns roles to admin users
7. ✅ Creates 14-day trial licence
8. ✅ Seeds sample data (plans, users, routers)
9. ✅ Verifies setup completion

**Script Options**:
```bash
# Skip sample data (only create essentials)
python scripts/setup_complete.py --skip-sample-data

# Fresh install (DANGER: Deletes all data!)
python scripts/setup_complete.py --fresh-install
```

#### Alternative: Manual Step-by-Step Setup

**Step 1: Run Database Migrations**
```bash
# Run migrations
alembic upgrade head

# Verify migrations
alembic current
```

**Step 2: Create Admin Accounts**
```bash
python scripts/create_admin.py
```

**Step 3: Seed Specific Data (Optional)**
```bash
# Seed only plans
python scripts/seed_plans.py

# Seed only users
python scripts/seed_users.py

# Seed only routers
python scripts/seed_routers.py
```

**Note**: The system automatically creates admin accounts on first startup via middleware:
- **Superuser**: `superuser` / `superuser123`
- **Demo Admin**: `demo` / `demo123`

---

## Frontend Setup

### 1. Configure Environment Variables

#### Step 1: Copy Environment Template
```bash
cd wifi-billing-software-frontend
cp .env.example .env.local
```

#### Step 2: Edit `.env.local` File
```bash
# Open with your preferred editor
nano .env.local
# or
code .env.local
```

#### Step 3: Configure Required Variables
```ini
# API Configuration
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000

# Application Settings
NEXT_PUBLIC_APP_NAME="Codevertex ISP Billing"
NEXT_PUBLIC_APP_VERSION=1.0.0

# Feature Flags
NEXT_PUBLIC_ENABLE_DEMO_MODE=true
NEXT_PUBLIC_ENABLE_REGISTRATION=true

# Analytics (Optional)
NEXT_PUBLIC_GA_TRACKING_ID=
NEXT_PUBLIC_SENTRY_DSN=

# Map Provider (Optional)
NEXT_PUBLIC_MAPBOX_TOKEN=

# Other Services (Optional)
NEXT_PUBLIC_STRIPE_PUBLIC_KEY=
NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=
```

### 2. Build Frontend Assets

#### Development Build (for local testing)
```bash
npm run dev
# Frontend will be available at http://localhost:3000
```

#### Production Build
```bash
npm run build
npm run start
```

---

## Initial Configuration

### 1. Backend Auto-Configuration

When the backend starts for the first time, it automatically:

#### ✅ Creates System Roles
- **Superuser** - Full system access
- **Admin** - ISP provider administrator
- **Technician** - Technical support staff
- **Customer** - End users

#### ✅ Creates Permissions
- 14 permission modules
- 5 actions per module (READ, CREATE, UPDATE, DELETE, MANAGE)
- Total: 70 permissions

#### ✅ Seeds Demo Accounts
- **Superuser Account**:
  - Username: `superuser`
  - Password: `superuser123`
  - Role: Superuser
  - Access: Full system access

- **Demo Admin Account**:
  - Username: `demo`
  - Password: `demo123`
  - Role: Admin
  - Access: ISP provider features

#### ✅ Creates Demo Licence
- Licence Key: `DEMO-TRIAL-2024`
- Type: 14-day free trial
- Organization: Demo ISP Company
- Status: Active

### 2. Manual Configuration (Optional)

#### Configure System Settings via API

Once the backend is running, you can configure:

1. **General Settings**
   - Company name
   - Logo
   - Contact information
   - Terms and conditions

2. **Payment Gateway**
   - M-Pesa configuration
   - Paybill/Till number
   - API credentials

3. **SMS Gateway**
   - Provider selection
   - API credentials
   - Sender ID

4. **PPPoE Settings**
   - Network configuration
   - IP pool settings
   - DNS servers

5. **Hotspot Settings**
   - Landing page customization
   - Session timeout
   - Bandwidth limits

6. **Notification Settings**
   - Email templates
   - SMS templates
   - Notification triggers

---

## Running the Application

### 1. Start Backend Server

#### Development Mode (with auto-reload)
```bash
cd wifi-billing-software-backend
source venv/bin/activate  # Linux/MacOS
# or
venv\Scripts\activate  # Windows

# Start server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Production Mode
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### Using Gunicorn (Linux/MacOS - Production)
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

**Backend will be available at**: http://localhost:8000

### 2. Start Celery Worker (Optional)

If using background tasks:
```bash
# In a new terminal
cd wifi-billing-software-backend
source venv/bin/activate  # Linux/MacOS
# or
venv\Scripts\activate  # Windows

# Start Celery worker
celery -A app.core.celery worker --loglevel=info
```

### 3. Start Celery Beat (Optional)

For scheduled tasks:
```bash
# In another new terminal
cd wifi-billing-software-backend
source venv/bin/activate

# Start Celery beat
celery -A app.core.celery beat --loglevel=info
```

### 4. Start Frontend Server

#### Development Mode
```bash
cd wifi-billing-software-frontend

# Start Next.js development server
npm run dev
```

#### Production Mode
```bash
# Build for production
npm run build

# Start production server
npm run start
```

**Frontend will be available at**: http://localhost:3000

---

## Verification

### 1. Check Backend Health

#### API Documentation
Visit: http://localhost:8000/docs

You should see the Swagger UI with all API endpoints.

#### Health Check Endpoint
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected"
}
```

#### Test Authentication
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "demo",
    "password": "demo123"
  }'
```

Expected response:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "demo",
    "email": "demo@codevertexitsolutions.com",
    "role": "admin"
  }
}
```

### 2. Check Frontend

#### Home Page
Visit: http://localhost:3000

You should see the marketing landing page.

#### Login Page
Visit: http://localhost:3000/login

Try logging in with:
- Username: `demo`
- Password: `demo123`

#### Dashboard
After login, you should be redirected to: http://localhost:3000/dashboard

### 3. Check Database

#### Verify Tables
```bash
psql -U isp_admin -d isp_billing

# List all tables
\dt

# Check users table
SELECT id, username, email, role FROM users;

# Check roles table
SELECT id, name, description FROM roles;

# Exit
\q
```

### 4. Check Redis (Optional)

```bash
redis-cli

# Check keys
KEYS *

# Exit
exit
```

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Database Connection Error
**Error**: `Could not connect to database`

**Solutions**:
- Verify PostgreSQL is running:
  ```bash
  # Linux
  sudo systemctl status postgresql
  
  # MacOS
  brew services list
  
  # Windows
  # Check Services app for PostgreSQL service
  ```

- Check database credentials in `.env`
- Verify database exists:
  ```bash
  psql -U postgres -c "\l" | grep isp_billing
  ```

#### 2. Migration Errors
**Error**: `Target database is not up to date`

**Solutions**:
```bash
# Check current migration
alembic current

# Show migration history
alembic history

# Upgrade to latest
alembic upgrade head

# If issues persist, downgrade and re-upgrade
alembic downgrade -1
alembic upgrade head
```

#### 3. Port Already in Use
**Error**: `Address already in use`

**Solutions**:

**Backend (Port 8000)**:
```bash
# Linux/MacOS
lsof -ti:8000 | xargs kill -9

# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**Frontend (Port 3000)**:
```bash
# Linux/MacOS
lsof -ti:3000 | xargs kill -9

# Windows
netstat -ano | findstr :3000
taskkill /PID <PID> /F
```

#### 4. Module Import Errors
**Error**: `ModuleNotFoundError: No module named 'X'`

**Solutions**:
```bash
# Ensure virtual environment is activated
source venv/bin/activate  # Linux/MacOS
venv\Scripts\activate  # Windows

# Reinstall dependencies
pip install -r requirements.txt

# Clear Python cache
find . -type d -name "__pycache__" -exec rm -r {} +
```

#### 5. Frontend Build Errors
**Error**: `Module not found` or `Cannot find module`

**Solutions**:
```bash
# Clear node_modules and cache
rm -rf node_modules
rm -rf .next
rm package-lock.json

# Reinstall dependencies
npm install

# Clear npm cache if needed
npm cache clean --force
```

#### 6. CORS Errors
**Error**: `CORS policy: No 'Access-Control-Allow-Origin' header`

**Solutions**:
- Update `ALLOWED_ORIGINS` in backend `.env`:
  ```ini
  ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
  ```

- Ensure frontend `NEXT_PUBLIC_API_BASE_URL` is correct:
  ```ini
  NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
  ```

#### 7. Redis Connection Error (Optional)
**Error**: `Could not connect to Redis`

**Solutions**:
```bash
# Check if Redis is running
redis-cli ping

# Start Redis
# Linux
sudo systemctl start redis-server

# MacOS
brew services start redis

# Windows (Docker)
docker start redis
```

#### 8. Permission Denied Errors
**Error**: `Permission denied` when running scripts

**Solutions**:
```bash
# Make scripts executable (Linux/MacOS)
chmod +x scripts/*.py
chmod +x scripts/*.sh

# Run with python explicitly
python scripts/seed_all.py
```

---

## Additional Resources

### Documentation Links
- [API Documentation](./API_DOCUMENTATION.md)
- [RBAC System Guide](./RBAC_SYSTEM.md)
- [MikroTik Provisioning Guide](./MIKROTIK_PROVISIONING.md)
- [Bug Fixes Log](./BUG_FIXES.md)
- [Implementation Progress](../wifi-billing-software-frontend/docs/IMPLEMENTATION_PROGRESS.md)
- [Swagger Authentication Guide](./swagger_authentication_guide.md)

### Quick Commands Reference

#### Backend
```bash
# Activate virtual environment
source venv/bin/activate  # Linux/MacOS
venv\Scripts\activate  # Windows

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run migrations
alembic upgrade head

# Create admin user
python scripts/create_admin.py

# Seed data
python scripts/seed_all.py
```

#### Frontend
```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Start production server
npm run start
```

#### Database
```bash
# Access database
psql -U isp_admin -d isp_billing

# Create backup
pg_dump -U isp_admin isp_billing > backup.sql

# Restore backup
psql -U isp_admin isp_billing < backup.sql
```

---

## Next Steps

After successful setup:

1. ✅ **Login to the system**
   - Use demo credentials: `demo` / `demo123`
   - Or superuser: `superuser` / `superuser123`

2. ✅ **Configure system settings**
   - Update company information
   - Upload logo
   - Configure payment gateway
   - Setup SMS gateway

3. ✅ **Create service plans**
   - Define internet packages
   - Set pricing
   - Configure bandwidth limits

4. ✅ **Add MikroTik routers**
   - Connect your routers
   - Run provisioning wizard
   - Verify connectivity

5. ✅ **Create customer accounts**
   - Add users
   - Assign packages
   - Manage subscriptions

6. ✅ **Test end-to-end workflows**
   - User registration
   - Package purchase
   - Payment processing
   - Service activation

---

## Support

For issues, questions, or contributions:

- **Email**: support@codevertexitsolutions.com
- **Documentation**: See `/docs` folder
- **GitHub Issues**: Create an issue in the repository

---

**Last Updated**: October 21, 2025
**Version**: 1.0.0
**Author**: Codevertex Africa Limited

