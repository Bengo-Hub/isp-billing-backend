# Database Scripts - Codevertex ISP Billing System

## Overview
This directory contains utility scripts for database management, seeding, and system initialization.

> **Note:** Seed scripts have been consolidated under `scripts/seeds/` and helper utilities under `scripts/tools/`. The `scripts/tools/` folder has been restored and contains maintenance helpers such as `drop_db.py` and `migration_fk_fixer.py`.

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

#### `seed_all.py`
Seed all sample data.

```bash
python scripts/seed_all.py
```

#### `seed_plans.py`
Seed service plans.

```bash
python scripts/seed_plans.py
```

#### `seed_users.py`
Seed demo users.

```bash
python scripts/seed_users.py
```

#### `seed_routers.py`
Seed sample routers.

```bash
python scripts/seed_routers.py
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

