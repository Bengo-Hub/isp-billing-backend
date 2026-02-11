# Database Scripts - Codevertex ISP Billing System

## Overview
This directory contains utility scripts for database management, seeding, and system initialization.

---

## 🚀 Primary Script

### `setup_complete.py` ⭐ **RECOMMENDED**

**The all-in-one setup script** that handles everything you need to get started.

**Usage**:
```bash
python scripts/setup_complete.py
```

**What it does**:
1. ✅ Runs all Alembic database migrations
2. ✅ Cleans expired sessions and old data
3. ✅ Initializes RBAC system (roles and permissions)
4. ✅ Creates superuser account (`superuser` / `superuser123`)
5. ✅ Creates demo admin account (`demo` / `demo123`)
6. ✅ Assigns RBAC roles to admin users
7. ✅ Creates 14-day trial licence
8. ✅ Seeds sample data (plans, users, routers)
9. ✅ Verifies setup completion

**Options**:
```bash
# Skip sample data
python scripts/setup_complete.py --skip-sample-data

# Fresh install (⚠️ Deletes all data!)
python scripts/setup_complete.py --fresh-install
```

---

## Individual Scripts

### Initialization Scripts

#### `init_db.py`
Initialize database with basic structure.

```bash
python scripts/init_db.py
```

#### `create_admin.py`
Create initial admin user interactively.

```bash
python scripts/create_admin.py
```

---

### Seeding Scripts

All seed scripts are grouped under `scripts/seeds/` for clarity. Use `run_seeds.py` for interactive seeding or individual modules for automation.

#### Interactive runner

```bash
python scripts/seeds/run_seeds.py
```

#### Programmatic / CI runner

```bash
python scripts/run_prod_seed.py  # Seeds production essentials (RBAC, platform admin, tiers)
```

#### Individual seed modules

You can also invoke individual seed modules directly (useful for testing):

```bash
python scripts/seeds/seed_plans.py
python scripts/seeds/seed_users.py
python scripts/seeds/seed_demo_users.py
```
---

## Common Use Cases

### First-Time Setup
```bash
python scripts/setup_complete.py
```

### Reset Database
```bash
python scripts/setup_complete.py --fresh-install
```

### Update After Code Changes
```bash
alembic upgrade head
python scripts/setup_complete.py --skip-sample-data
```

---

**Last Updated**: October 21, 2025

