# ISP Billing System - Data Seeding Scripts

This directory contains comprehensive data seeding scripts for the ISP Billing System. These scripts generate realistic demo data for development, testing, and demonstration purposes.

## 🎯 Overview

The seeding system provides:
- **Realistic Data Generation**: Creates authentic ISP billing data with proper relationships
- **Configurable Options**: Customize the number of records to generate
- **Production-Ready**: Proper error handling, logging, and transaction management
- **Modular Design**: Individual scripts for each data type plus a master orchestrator

## 📁 File Structure

```
scripts/
├── seed_env.py              # Environment setup for seeding
├── seed_users.py            # User accounts and settings
├── seed_plans.py            # Service plans and package templates  
├── seed_routers.py          # MikroTik routers and devices
├── seed_licences.py         # Centipid licence management
├── seed_subscriptions.py    # Customer subscriptions and billing
├── seed_all.py              # Master orchestrator script
├── run_seeds.py             # Interactive script runner
└── README.md                # This file
```

## 🚀 Quick Start

### Option 1: Interactive Runner
```bash
cd backend/scripts
python run_seeds.py
```

### Option 2: Command Line
```bash
cd backend/scripts

# Seed with defaults (50 users, 20 plans, 10 routers, etc.)
python seed_all.py --clear

# Seed minimal data for development
python seed_all.py --clear --users 10 --plans 5 --routers 3 --subscriptions 20

# Seed large dataset for testing
python seed_all.py --clear --users 500 --plans 50 --routers 25 --subscriptions 1000
```

### Option 3: Individual Scripts
```bash
# Seed only users
python seed_users.py

# Seed only plans
python seed_plans.py

# Seed only routers
python seed_routers.py
```

## 📊 Generated Data

### 👥 Users (`seed_users.py`)
- **1 Admin User**: `admin` / `admin123` - Full system access
- **3 Technician Users**: `tech1`, `tech2`, `support` / `tech123` - Device and customer management
- **46+ Customer Users**: Realistic names, emails, phones with varied verification status
- **User Settings**: Theme preferences, notification settings, UI configurations

**Default Admin Credentials:**
- Username: `admin`
- Password: `admin123`
- Email: `admin@ispbilling.com`

### 📦 Service Plans (`seed_plans.py`)
- **Hotspot Plans**: 1GB Basic, 5GB Standard, Unlimited Premium
- **PPPoE Plans**: Home Basic (5Mbps), Home Standard (10Mbps), Business (20Mbps), Enterprise (50Mbps)
- **Package Templates**: Student, Family, Business Starter, Free Trial, Data-only packages
- **Package Categories**: Hotspot, PPPoE, Data Plans, Free Trial with configurations
- **Realistic Pricing**: KES pricing with proper billing cycles

### 🌐 Routers (`seed_routers.py`)
- **Standard Routers**: Main Office, Branch Office, Hotspot, Residential, Backup routers
- **Router Devices**: Connected devices with realistic MAC addresses and usage
- **Router Logs**: Operation history with success/failure patterns
- **Locations**: Kenyan cities with GPS coordinates
- **Configurations**: Complete MikroTik RouterOS configurations

### 🔑 Licences (`seed_licences.py`)
- **Licence Types**: Trial, Basic, Professional, Enterprise
- **Payment History**: 3-12 months of payment records
- **Usage Tracking**: Daily usage logs with realistic patterns
- **Features**: Feature availability by licence type
- **Organizations**: Realistic ISP company names and contacts

### 📱 Subscriptions (`seed_subscriptions.py`)
- **Customer Subscriptions**: Hotspot and PPPoE subscriptions
- **Billing Data**: Invoices, payments, usage logs
- **Payment Methods**: MPESA, Bank Transfer, Cash with realistic patterns
- **Usage Patterns**: Realistic data usage and session patterns
- **Status Variety**: Active, expired, suspended, pending subscriptions

## ⚙️ Configuration Options

### Master Script Options
```bash
python seed_all.py [OPTIONS]

Options:
  --clear                 Clear existing data before seeding
  --users N              Number of users to seed (default: 50)
  --plans N              Number of plans to seed (default: 20)  
  --routers N            Number of routers to seed (default: 10)
  --licences N           Number of licences to seed (default: 5)
  --subscriptions N      Number of subscriptions to seed (default: 100)
  --package-templates N  Number of package templates to seed (default: 15)
  --skip MODEL [MODEL...] Skip specific models
  --only MODEL [MODEL...]  Only seed specific models
  --clear-only           Only clear data, don't seed
  --quiet                Reduce output verbosity
```

### Environment Variables
The scripts automatically detect and use your `.env` file, or fall back to defaults:
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ispbilling
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
# ... other variables
```

## 📈 Data Relationships

The seeding system maintains proper foreign key relationships:

```
Users (Admin, Technicians, Customers)
├── UserSettings (UI preferences)
├── Subscriptions
│   ├── ServicePlans (with pricing and features)
│   ├── Routers (with devices and logs)
│   ├── Invoices (with items and payments)
│   └── UsageLogs
├── Licences (with payments and usage)
└── PackageTemplates (with assignments)
```

## 🛡️ Production Readiness

### Security Features
- **Password Hashing**: Bcrypt hashing for all user passwords
- **Input Validation**: Comprehensive validation of all generated data
- **SQL Injection Prevention**: Parameterized queries throughout
- **Error Handling**: Graceful error handling with detailed logging

### Performance Features
- **Async Operations**: Full async/await support for optimal performance
- **Batch Processing**: Efficient batch inserts for large datasets
- **Transaction Management**: Atomic operations with rollback on failure
- **Connection Pooling**: Proper database connection management

### Data Quality
- **Realistic Data**: Names, emails, phones, addresses from real patterns
- **Proper Relationships**: Maintains referential integrity
- **Varied Status**: Realistic distribution of active/inactive/pending states
- **Time-based Data**: Proper date relationships and aging

## 🔧 Development Usage

### Development Environment
```bash
# Minimal data for development
python seed_all.py --clear --users 10 --plans 5 --routers 3 --subscriptions 20
```

### Testing Environment
```bash
# Larger dataset for testing
python seed_all.py --clear --users 100 --plans 25 --routers 15 --subscriptions 300
```

### Demo Environment
```bash
# Full demo dataset
python seed_all.py --clear --users 500 --plans 50 --routers 25 --subscriptions 1000
```

## 📝 Logging and Monitoring

All scripts provide comprehensive logging:
- **Progress Tracking**: Real-time progress updates
- **Error Reporting**: Detailed error messages and stack traces
- **Performance Metrics**: Execution time and record counts
- **SQL Logging**: Database query logging (configurable)

Example output:
```
🌱 STARTING MASTER SEED PROCESS
📋 Models to seed: users, licences, plans, routers, subscriptions
📊 Seed counts: {'users': 50, 'plans': 20, 'routers': 10, ...}

🌱 Seeding users...
✅ users seeded successfully: 50 records
🌱 Seeding licences...
✅ licences seeded successfully: 5 records

🎉 MASTER SEED PROCESS COMPLETED
📊 Total records created: 1,245
✅ Successful models: 6
⏱️  Total duration: 12.34 seconds
```

## 🚨 Important Notes

### Database Requirements
- **PostgreSQL**: Requires PostgreSQL database
- **Redis**: Requires Redis for caching (optional for seeding)
- **Migrations**: Run `alembic upgrade head` before seeding

### Data Clearing
- **--clear flag**: Completely clears existing data
- **Foreign Key Order**: Clears in proper order to respect relationships
- **Irreversible**: Data clearing cannot be undone

### Production Warnings
- **Never run on production**: These scripts are for development/testing only
- **Backup first**: Always backup production data before any operations
- **Environment separation**: Use separate databases for development

## 🎯 Next Steps

After seeding data:

1. **Start the API server**:
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. **Access API documentation**: http://localhost:8000/docs

3. **Login with admin credentials**:
   - Username: `admin`
   - Password: `admin123`

4. **Explore the data** through the API endpoints

## 🤝 Contributing

When adding new seed scripts:
1. Follow the existing pattern in `seed_users.py`
2. Include proper error handling and logging
3. Add to the master script `seed_all.py`
4. Update this README with new data types
5. Test with various record counts

## 📚 API Integration

The seeded data is immediately available through all API endpoints:
- `/api/v1/users` - User management
- `/api/v1/plans` - Service plans
- `/api/v1/routers` - Router management  
- `/api/v1/subscriptions` - Customer subscriptions
- `/api/v1/billing` - Billing and payments
- `/api/v1/licences` - Licence management

Visit http://localhost:8000/docs for complete API documentation.
