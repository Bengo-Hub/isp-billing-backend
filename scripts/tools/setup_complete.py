#!/usr/bin/env python3
"""
Complete Setup Script for Codevertex ISP Billing System

This script performs the following operations:
1. Run database migrations
2. Clean old/invalid data
3. Initialize RBAC system (roles and permissions)
4. Seed demo and superuser accounts
5. Assign roles to admin users
6. Create demo licence
7. Seed sample data (optional)

Usage:
    python scripts/setup_complete.py [--skip-sample-data] [--fresh-install]
    
Options:
    --skip-sample-data: Skip seeding sample plans, routers, etc.
    --fresh-install: Drop all tables and start fresh (DANGER!)
"""

import sys
import os
import argparse
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import subprocess
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text, or_, create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import engine as async_engine, Base
from app.core.security import get_password_hash
from app.core.config import settings
from app.models.user import User, UserRole, UserStatus
from app.models.rbac import Role, Permission, UserPermission, SystemLicence, PermissionModule, PermissionAction
from app.modules.auth import RBACService


# Create synchronous engine for setup operations
sync_database_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql://", "postgresql://")
if not sync_database_url.startswith("postgresql://"):
    sync_database_url = "postgresql://" + sync_database_url

sync_engine = create_engine(sync_database_url, echo=settings.debug)

# Create session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def print_header(message: str):
    """Print formatted header."""
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80 + "\n")


def print_step(step: int, total: int, message: str):
    """Print step progress."""
    print(f"[{step}/{total}] {message}...")


def print_success(message: str):
    """Print success message."""
    print(f"✓ {message}")


def print_error(message: str):
    """Print error message."""
    print(f"✗ ERROR: {message}")


def run_migrations(skip_migrations=False):
    """Run Alembic migrations or stamp if after fresh install."""
    print_header("Step 1: Running Database Migrations")
    
    try:
        # Check if alembic is available
        result = subprocess.run(
            ["alembic", "current"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print_error("Alembic not found or not configured")
            return False
        
        if skip_migrations:
            # After fresh install, just stamp the database to the latest version
            print("Stamping database to latest migration (head)...")
            result = subprocess.run(
                ["alembic", "stamp", "head"],
                capture_output=True,
                text=True,
                check=True
            )
            print_success("Database stamped to latest migration")
        else:
            # Run migrations normally
            print("Running: alembic upgrade head")
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                check=True
            )
            print(result.stdout)
            print_success("Migrations completed successfully")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print_error(f"Migration failed: {e.stderr}")
        return False
    except Exception as e:
        print_error(f"Migration error: {str(e)}")
        return False


def clean_old_data(db: Session):
    """Clean old/invalid data from database."""
    print_header("Step 2: Cleaning Old Data")
    
    try:
        # Delete expired sessions
        print("Removing expired user sessions...")
        result = db.execute(
            text("DELETE FROM user_sessions WHERE expires_at < NOW()")
        )
        print_success(f"Removed {result.rowcount} expired sessions")
        
        # Delete old provisioning logs (older than 30 days)
        print("Removing old provisioning logs...")
        result = db.execute(
            text("DELETE FROM provisioning_logs WHERE created_at < NOW() - INTERVAL '30 days'")
        )
        print_success(f"Removed {result.rowcount} old provisioning logs")
        
        # Delete orphaned user permissions (users that don't exist)
        print("Removing orphaned user permissions...")
        result = db.execute(
            text("""
                DELETE FROM user_permissions 
                WHERE user_id NOT IN (SELECT id FROM users)
            """)
        )
        print_success(f"Removed {result.rowcount} orphaned permissions")
        
        db.commit()
        print_success("Data cleanup completed")
        return True
        
    except Exception as e:
        print_error(f"Data cleanup error: {str(e)}")
        db.rollback()
        return False


def initialize_rbac_system(db: Session):
    """Initialize RBAC system with roles and permissions."""
    print_header("Step 3: Initializing RBAC System")
    
    try:
        rbac_service = RBACService(db)
        
        # Initialize system roles and permissions
        print("Creating system roles and permissions...")
        roles = rbac_service.initialize_system_roles_and_permissions()
        
        print_success(f"Created {len(roles)} system roles:")
        for role_name, role in roles.items():
            perm_count = len(role.permissions)
            print(f"  - {role_name}: {perm_count} permissions")
        
        db.commit()
        return roles
        
    except Exception as e:
        print_error(f"RBAC initialization error: {str(e)}")
        db.rollback()
        return None


def create_admin_accounts(db: Session, roles: dict):
    """Create superuser and demo admin accounts."""
    print_header("Step 4: Creating Admin Accounts")
    
    accounts_created = []
    
    try:
        # Hash passwords once at the start
        try:
            superuser_password_hash = get_password_hash("superuser123")
            demo_password_hash = get_password_hash("demo123")
        except Exception as e:
            print_error(f"Password hashing error: {str(e)}")
            # Fallback to simpler bcrypt if there's a version issue
            import bcrypt
            superuser_password_hash = bcrypt.hashpw("superuser123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            demo_password_hash = bcrypt.hashpw("demo123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # 1. Create/Update Superuser Account
        print("Setting up superuser account...")
        superuser = db.query(User).filter(User.username == "superuser").first()
        
        if not superuser:
            superuser = User(
                username="superuser",
                email="superuser@codevertexitsolutions.com",
                first_name="Super",
                last_name="User",
                company_name="Codevertex Africa Limited",
                hashed_password=superuser_password_hash,
                role=UserRole.SUPERUSER,
                status=UserStatus.ACTIVE,
                is_verified=True,
                is_active=True,
                role_id=roles["superuser"].id
            )
            db.add(superuser)
            db.flush()
            accounts_created.append("superuser")
            print_success("Superuser account created")
        else:
            # Update existing superuser
            superuser.hashed_password = superuser_password_hash
            superuser.role = UserRole.SUPERUSER
            superuser.status = UserStatus.ACTIVE
            superuser.is_verified = True
            superuser.is_active = True
            superuser.role_id = roles["superuser"].id
            print_success("Superuser account updated")
        
        # 2. Create/Update Demo Admin Account
        print("Setting up demo admin account...")
        demo_admin = db.query(User).filter(User.username == "demo").first()
        
        if not demo_admin:
            demo_admin = User(
                username="demo",
                email="demo@codevertexitsolutions.com",
                first_name="Demo",
                last_name="Admin",
                company_name="Demo ISP Company",
                hashed_password=demo_password_hash,
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
                is_verified=True,
                is_active=True,
                role_id=roles["admin"].id
            )
            db.add(demo_admin)
            db.flush()
            accounts_created.append("demo")
            print_success("Demo admin account created")
        else:
            # Update existing demo admin
            demo_admin.hashed_password = demo_password_hash
            demo_admin.role = UserRole.ADMIN
            demo_admin.status = UserStatus.ACTIVE
            demo_admin.is_verified = True
            demo_admin.is_active = True
            demo_admin.role_id = roles["admin"].id
            print_success("Demo admin account updated")
        
        db.commit()
        
        print_success(f"Admin accounts ready: {', '.join(['superuser', 'demo'])}")
        return True
        
    except Exception as e:
        print_error(f"Admin account creation error: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False


def assign_roles_to_admins(db: Session, roles: dict):
    """Assign appropriate roles to all admin users."""
    print_header("Step 5: Assigning Roles to Admin Users")
    
    try:
        # Get all users with admin or superuser roles
        admin_users = db.query(User).filter(
            or_(
                User.role == UserRole.ADMIN,
                User.role == UserRole.SUPERUSER
            )
        ).all()
        
        updated_count = 0
        for user in admin_users:
            if user.role == UserRole.SUPERUSER and not user.role_id:
                user.role_id = roles["superuser"].id
                updated_count += 1
                print(f"  - Assigned superuser role to: {user.username}")
            elif user.role == UserRole.ADMIN and not user.role_id:
                user.role_id = roles["admin"].id
                updated_count += 1
                print(f"  - Assigned admin role to: {user.username}")
        
        db.commit()
        print_success(f"Assigned roles to {updated_count} admin users")
        return True
        
    except Exception as e:
        print_error(f"Role assignment error: {str(e)}")
        db.rollback()
        return False


def create_demo_licence(db: Session):
    """Create demo trial licence."""
    print_header("Step 6: Creating Demo Licence")
    
    try:
        rbac_service = RBACService(db)
        
        # Check if demo licence exists
        demo_licence = db.query(SystemLicence).filter(
            SystemLicence.licence_key == "DEMO-TRIAL-2024"
        ).first()
        
        if not demo_licence:
            print("Creating demo trial licence...")
            demo_licence = rbac_service.create_system_licence(
                licence_key="DEMO-TRIAL-2024",
                organization_name="Demo ISP Company",
                contact_email="demo@codevertexitsolutions.com",
                contact_phone="+254 700 000 000",
                licence_type="trial",
                trial_days=14,
                max_users=100,
                max_routers=20
            )
            
            # Activate trial
            rbac_service.activate_licence_trial(demo_licence.id)
            print_success(f"Demo licence created: {demo_licence.licence_key}")
            print(f"  - Organization: {demo_licence.organization_name}")
            print(f"  - Trial Days: {demo_licence.trial_days}")
            print(f"  - Max Users: {demo_licence.max_users}")
            print(f"  - Max Routers: {demo_licence.max_routers}")
        else:
            print_success("Demo licence already exists")
        
        db.commit()
        return True
        
    except Exception as e:
        print_error(f"Licence creation error: {str(e)}")
        db.rollback()
        return False


def seed_sample_data(db: Session):
    """Seed sample data (plans, routers, users)."""
    print_header("Step 7: Seeding Sample Data")
    
    try:
        # Import seed functions
        from scripts.seed_plans import seed_plans
        from scripts.seed_users import seed_demo_users
        from scripts.seed_routers import seed_routers
        
        print("Seeding sample plans...")
        plans_created = seed_plans(db)
        print_success(f"Created {plans_created} sample plans")
        
        print("Seeding demo users...")
        users_created = seed_demo_users(db)
        print_success(f"Created {users_created} demo users")
        
        print("Seeding sample routers...")
        routers_created = seed_routers(db)
        print_success(f"Created {routers_created} sample routers")
        
        db.commit()
        print_success("Sample data seeding completed")
        return True
        
    except ImportError as e:
        print(f"⚠ Warning: Sample data scripts not found ({str(e)})")
        print("  Skipping sample data seeding...")
        return True
    except Exception as e:
        print_error(f"Sample data seeding error: {str(e)}")
        db.rollback()
        return False


def verify_setup(db: Session):
    """Verify that setup was successful."""
    print_header("Step 8: Verifying Setup")
    
    try:
        # Check roles
        roles_count = db.query(Role).count()
        print(f"✓ Roles created: {roles_count}")
        
        # Check permissions
        permissions_count = db.query(Permission).count()
        print(f"✓ Permissions created: {permissions_count}")
        
        # Check users
        users_count = db.query(User).count()
        print(f"✓ Total users: {users_count}")
        
        # Check admin accounts
        superuser = db.query(User).filter(User.username == "superuser").first()
        demo = db.query(User).filter(User.username == "demo").first()
        
        if superuser:
            print(f"✓ Superuser account: {superuser.username} (Role: {superuser.role.value})")
        else:
            print("✗ Superuser account NOT found!")
            
        if demo:
            print(f"✓ Demo admin account: {demo.username} (Role: {demo.role.value})")
        else:
            print("✗ Demo admin account NOT found!")
        
        # Check licence
        licences_count = db.query(SystemLicence).count()
        print(f"✓ System licences: {licences_count}")
        
        print_success("Setup verification completed")
        return True
        
    except Exception as e:
        print_error(f"Verification error: {str(e)}")
        return False


def fresh_install(db: Session):
    """Drop all tables and recreate (DANGER!)."""
    print_header("Fresh Install: Dropping All Tables")
    
    print("⚠️  WARNING: This will delete ALL data in the database!")
    print("⚠️  This action cannot be undone!")
    
    # Ask for confirmation
    confirmation = input("\nType 'YES' to confirm fresh install: ")
    
    if confirmation != "YES":
        print("Fresh install cancelled.")
        return False
    
    try:
        # Import all models to ensure they are registered
        from app.models import (  # noqa: F401
            user,
            router,
            plan,
            subscription,
            billing,
            notification,
            rbac,
        )
        
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=sync_engine)
        print_success("All tables dropped")
        
        print("Creating all tables...")
        Base.metadata.create_all(bind=sync_engine)
        print_success("All tables created")
        
        return True
        
    except Exception as e:
        print_error(f"Fresh install error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main setup function."""
    parser = argparse.ArgumentParser(
        description="Complete setup script for Codevertex ISP Billing System"
    )
    parser.add_argument(
        '--skip-sample-data',
        action='store_true',
        help='Skip seeding sample data'
    )
    parser.add_argument(
        '--fresh-install',
        action='store_true',
        help='Drop all tables and start fresh (DANGER!)'
    )
    
    args = parser.parse_args()
    
    print_header("Codevertex ISP Billing System - Complete Setup")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Database: {settings.database_url.split('@')[-1] if '@' in settings.database_url else 'Unknown'}")
    
    # Create database session
    db = SessionLocal()
    
    try:
        total_steps = 8 if not args.skip_sample_data else 7
        current_step = 0
        
        # Fresh install if requested
        fresh_installed = False
        if args.fresh_install:
            if not fresh_install(db):
                print_error("Fresh install failed. Exiting.")
                return 1
            fresh_installed = True
        
        # Step 1: Run migrations (or stamp if fresh install)
        current_step += 1
        if not run_migrations(skip_migrations=fresh_installed):
            print_error("Migration failed. Exiting.")
            return 1
        
        # Step 2: Clean old data
        current_step += 1
        clean_old_data(db)
        
        # Step 3: Initialize RBAC
        current_step += 1
        roles = initialize_rbac_system(db)
        if not roles:
            print_error("RBAC initialization failed. Exiting.")
            return 1
        
        # Step 4: Create admin accounts
        current_step += 1
        if not create_admin_accounts(db, roles):
            print_error("Admin account creation failed. Exiting.")
            return 1
        
        # Step 5: Assign roles
        current_step += 1
        if not assign_roles_to_admins(db, roles):
            print_error("Role assignment failed. Exiting.")
            return 1
        
        # Step 6: Create demo licence
        current_step += 1
        if not create_demo_licence(db):
            print_error("Licence creation failed. Exiting.")
            return 1
        
        # Step 7: Seed sample data (optional)
        if not args.skip_sample_data:
            current_step += 1
            seed_sample_data(db)
        
        # Step 8: Verify setup
        current_step += 1
        verify_setup(db)
        
        # Print final summary
        print_header("Setup Completed Successfully!")
        print("\n📋 Summary:")
        print("  ✓ Database migrations applied")
        print("  ✓ Old data cleaned")
        print("  ✓ RBAC system initialized")
        print("  ✓ Admin accounts created")
        print("  ✓ Roles assigned")
        print("  ✓ Demo licence created")
        if not args.skip_sample_data:
            print("  ✓ Sample data seeded")
        
        print("\n🔐 Admin Credentials:")
        print("  Superuser: superuser / superuser123")
        print("  Demo Admin: demo / demo123")
        
        print("\n🚀 Next Steps:")
        print("  1. Start the backend server:")
        print("     uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
        print("\n  2. Access Swagger UI:")
        print("     http://localhost:8000/docs")
        print("\n  3. Login with demo credentials:")
        print("     Username: demo")
        print("     Password: demo123")
        
        print(f"\n✅ Setup completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        return 1
    except Exception as e:
        print_error(f"Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

