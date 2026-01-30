"""Master seed script for seeding all demo data with configurable options."""

import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger

# Import individual seed functions
from seed_organizations import seed_platform_tiers, seed_organizations
from seed_rbac import seed_rbac
from seed_users import seed_users
from seed_plans import seed_plans, seed_package_templates, seed_package_categories
from seed_routers import seed_routers
from seed_licences import seed_licences
from seed_subscriptions import seed_subscriptions

logger = get_logger(__name__)


class MasterSeeder:
    """Master seeder for all system data with multi-tenancy support."""

    def __init__(self):
        self.logger = get_logger(__name__)

        # Default seed counts
        self.default_counts = {
            "users": 50,
            "plans": 10,
            "package_templates": 15,
            "routers": 10,
            "licences": 5,
            "subscriptions": 50
        }

        # Seed order (important for foreign key dependencies)
        # Organizations must come before users, routers, plans, etc.
        self.seed_order = [
            "platform_tiers",      # Platform subscription tiers first
            "organizations",       # ISP providers (tenants)
            "rbac",                # Roles & permissions
            "users",               # Platform owner, ISP admins, technicians, customers
            "licences",
            "package_categories",
            "package_templates",
            "plans",
            "routers",
            "subscriptions"
        ]

    async def seed_all(
        self, 
        clear_existing: bool = False,
        counts: Dict[str, int] = None,
        skip_models: list = None,
        only_models: list = None
    ) -> Dict[str, Any]:
        """Seed all data with configurable options."""
        start_time = datetime.utcnow()
        
        # Use provided counts or defaults
        seed_counts = {**self.default_counts, **(counts or {})}
        skip_models = skip_models or []
        
        # Filter models if only_models is specified
        if only_models:
            models_to_seed = [model for model in self.seed_order if model in only_models]
        else:
            models_to_seed = [model for model in self.seed_order if model not in skip_models]
        
        results = {}
        
        self.logger.info("=" * 60)
        self.logger.info("[SEED] STARTING MASTER SEED PROCESS")
        self.logger.info("=" * 60)
        
        if clear_existing:
            self.logger.warning("[WARN]  CLEARING ALL EXISTING DATA")
            # Ensure DB enums are complete (adds missing billing cycle values if needed)
            try:
                from ensure_billingcycle_values import ensure_billingcycle_values
                await ensure_billingcycle_values()
            except Exception:
                self.logger.exception("Failed to ensure billing cycle enum values, continuing")

            # Perform a full clear first to ensure a clean state before seeding
            # Ensure system-level tables that reference users are cleared first to avoid FK issues
            await self._clear_system_level_data()
            await self.clear_all_data()
            clear_existing = False

        # List models to seed for visibility
        self.logger.info(f"[LIST] Models to seed: {', '.join(models_to_seed)}")
        self.logger.info(f"[CHART] Seed counts: {seed_counts}")
        
        try:
            # Seed each model in order
            for model_name in models_to_seed:
                self.logger.info(f"[SEED] Seeding {model_name}...")

                try:
                    if model_name == "platform_tiers":
                        result = await seed_platform_tiers(clear_existing=clear_existing)
                        results["platform_tiers"] = {"count": len(result), "status": "success"}

                    elif model_name == "organizations":
                        result = await seed_organizations(clear_existing=clear_existing)
                        results["organizations"] = {"count": len(result), "status": "success"}

                    elif model_name == "rbac":
                        result = await seed_rbac(clear_existing=clear_existing)
                        results["rbac"] = {"count": len(result), "status": "success"}

                    elif model_name == "users":
                        result = await seed_users(
                            count=seed_counts["users"],
                            clear_existing=clear_existing
                        )
                        results["users"] = {"count": len(result), "status": "success"}

                    elif model_name == "licences":
                        result = await seed_licences(
                            count=seed_counts["licences"],
                            clear_existing=clear_existing
                        )
                        results["licences"] = {"count": len(result), "status": "success"}

                    elif model_name == "package_categories":
                        result = await seed_package_categories(clear_existing=clear_existing)
                        results["package_categories"] = {"count": len(result), "status": "success"}

                    elif model_name == "package_templates":
                        result = await seed_package_templates(
                            count=seed_counts["package_templates"],
                            clear_existing=clear_existing
                        )
                        results["package_templates"] = {"count": len(result), "status": "success"}

                    elif model_name == "plans":
                        result = await seed_plans(
                            count=seed_counts["plans"],
                            clear_existing=clear_existing
                        )
                        results["plans"] = {"count": len(result), "status": "success"}

                    elif model_name == "routers":
                        result = await seed_routers(
                            count=seed_counts["routers"],
                            clear_existing=clear_existing
                        )
                        results["routers"] = {"count": len(result), "status": "success"}

                    elif model_name == "subscriptions":
                        result = await seed_subscriptions(
                            count=seed_counts["subscriptions"],
                            clear_existing=clear_existing
                        )
                        results["subscriptions"] = {"count": len(result), "status": "success"}

                    self.logger.info(f"[OK] {model_name} seeded successfully: {results[model_name]['count']} records")

                    # Clear existing flag after first model to avoid clearing dependencies
                    clear_existing = False

                except Exception as e:
                    self.logger.error(f"[FAIL] Failed to seed {model_name}: {e}")
                    results[model_name] = {"count": 0, "status": "failed", "error": str(e)}
            
            # Additional system data
            await self._seed_system_data()
            
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            # Calculate totals
            total_records = sum(r.get("count", 0) for r in results.values())
            successful_models = sum(1 for r in results.values() if r.get("status") == "success")
            failed_models = sum(1 for r in results.values() if r.get("status") == "failed")
            
            self.logger.info("=" * 60)
            self.logger.info("[DONE] MASTER SEED PROCESS COMPLETED")
            self.logger.info("=" * 60)
            self.logger.info(f"[CHART] Total records created: {total_records}")
            self.logger.info(f"[OK] Successful models: {successful_models}")
            self.logger.info(f"[FAIL] Failed models: {failed_models}")
            self.logger.info(f"[TIME]️  Total duration: {duration:.2f} seconds")
            
            return {
                "status": "completed",
                "total_records": total_records,
                "successful_models": successful_models,
                "failed_models": failed_models,
                "duration_seconds": duration,
                "results": results,
                "completed_at": end_time.isoformat()
            }
            
        except Exception as e:
            import traceback
            self.logger.error(f"[ERROR] Master seed process failed: {e}")
            self.logger.error(traceback.format_exc())
            return {
                "status": "failed",
                "error": str(e),
                "results": results,
                "completed_at": datetime.utcnow().isoformat()
            }

    async def _clear_system_level_data(self):
        """Clear system-level data that must be removed before deleting users."""
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            from app.models.notification import NotificationTemplate
            from app.models.user_settings import UIPreferences
            from app.models.configuration import Configuration

            await db.execute(delete(NotificationTemplate))
            await db.execute(delete(UIPreferences))
            await db.execute(delete(Configuration))
            await db.commit()
            self.logger.info("Cleared system-level data (notifications, ui prefs, configurations)")

    async def _seed_system_data(self):
        """Seed additional system data."""
        async with AsyncSessionLocal() as db:
            # Seed notification templates
            await self._seed_notification_templates(db)
            
            # Seed UI preferences
            await self._seed_ui_preferences(db)
            
            # Seed configuration settings
            await self._seed_configuration_settings(db)

    async def _seed_notification_templates(self, db: AsyncSession):
        """Seed notification templates."""
        import json
        from app.models.notification import NotificationTemplate, NotificationType
        from app.models.user import User

        # Get first admin user for created_by
        result = await db.execute(
            select(User).limit(1)
        )
        admin_user = result.scalar_one_or_none()
        if not admin_user:
            self.logger.warning("[WARN] No user found for notification templates created_by, skipping")
            return

        templates = [
            # Email Templates
            {
                "name": "Welcome Email",
                "notification_type": NotificationType.WELCOME,
                "subject_template": "Welcome to {company_name}",
                "body_template": """
                <h1>Welcome {customer_name}!</h1>
                <p>Thank you for choosing {company_name} for your internet needs.</p>
                <p>Your account details:</p>
                <ul>
                    <li>Username: {username}</li>
                    <li>Plan: {plan_name}</li>
                    <li>Speed: {download_speed}Mbps</li>
                </ul>
                <p>If you have any questions, please contact our support team.</p>
                """,
                "variables": json.dumps(["company_name", "customer_name", "username", "plan_name", "download_speed"]),
                "is_active": True
            },
            {
                "name": "Service Expiry Reminder",
                "notification_type": NotificationType.SUBSCRIPTION,
                "subject_template": None,
                "body_template": "Hi {customer_name}, your {plan_name} expires on {expiry_date}. Renew now to avoid service interruption. Pay via MPESA: {paybill_number}",
                "variables": json.dumps(["customer_name", "plan_name", "expiry_date", "paybill_number"]),
                "is_active": True
            },
            # SMS Templates
            {
                "name": "subscription_success",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Dear {username}, you have successfully subscribed to {plan_name}. Your subscription will expire on {expiry_date}. Your username is {username} and password is {password}.",
                "hotspot_template": "Dear {username}, you have successfully subscribed to {plan_name}. Expires: {expiry_date}. Username: {username}, Password: {password}.",
                "pppoe_template": "Dear {username}, your PPPoE subscription to {plan_name} is now active. Expires: {expiry_date}. Username: {username}, Password: {password}.",
                "description": "Sent when a customer successfully subscribes to a plan",
                "category": "subscription",
                "variables": json.dumps(["username", "plan_name", "expiry_date", "password"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "subscription_expiry_reminder",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Hi {username}, your {plan_name} subscription expires on {expiry_date}. Renew now to continue enjoying uninterrupted service. Visit {portal_url} or pay via M-PESA.",
                "hotspot_template": "Hi {username}, your hotspot package {plan_name} expires on {expiry_date}. Renew to stay connected!",
                "pppoe_template": "Hi {username}, your PPPoE subscription {plan_name} expires on {expiry_date}. Renew to avoid disconnection.",
                "description": "Sent to remind customers before their subscription expires",
                "category": "subscription",
                "variables": json.dumps(["username", "plan_name", "expiry_date", "portal_url"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "subscription_expired",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Dear {username}, your {plan_name} subscription has expired. Renew now at {portal_url} to restore your internet access.",
                "hotspot_template": "Dear {username}, your hotspot package has expired. Buy a new package to get back online.",
                "pppoe_template": "Dear {username}, your PPPoE subscription has expired. Please renew to restore your connection.",
                "description": "Sent when a customer's subscription expires",
                "category": "subscription",
                "variables": json.dumps(["username", "plan_name", "portal_url"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "payment_received",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Payment of {currency} {amount} received. Transaction ID: {transaction_id}. Thank you for your payment!",
                "hotspot_template": "Payment of {currency} {amount} received for {plan_name}. Your hotspot is now active. Enjoy browsing!",
                "pppoe_template": "Payment of {currency} {amount} received for {plan_name}. Your PPPoE subscription has been activated.",
                "description": "Sent when a payment is successfully processed",
                "category": "billing",
                "variables": json.dumps(["currency", "amount", "transaction_id", "plan_name"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "welcome_sms",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Welcome to {company_name}! Your account has been created. Username: {username}. Visit {portal_url} to manage your subscription.",
                "hotspot_template": "Welcome to {company_name}! Connect to our WiFi hotspot and use username: {username} to login.",
                "pppoe_template": "Welcome to {company_name}! Your PPPoE account is ready. Username: {username}. Contact support if you need help setting up.",
                "description": "Sent when a new customer account is created",
                "category": "welcome",
                "variables": json.dumps(["company_name", "username", "portal_url"]),
                "user_type_specific": True,
                "is_active": True
            },
        ]

        for template_data in templates:
            template = NotificationTemplate(
                name=template_data["name"],
                notification_type=template_data["notification_type"],
                subject_template=template_data.get("subject_template"),
                body_template=template_data["body_template"],
                hotspot_template=template_data.get("hotspot_template"),
                pppoe_template=template_data.get("pppoe_template"),
                description=template_data.get("description"),
                category=template_data.get("category"),
                variables=template_data.get("variables"),
                user_type_specific=template_data.get("user_type_specific", False),
                is_active=template_data.get("is_active", True),
                created_by=admin_user.id,
                created_at=datetime.utcnow()
            )

            db.add(template)

        await db.commit()
        self.logger.info("[OK] Seeded notification templates (including 5 SMS templates)")

    async def _seed_ui_preferences(self, db: AsyncSession):
        """Seed UI preferences."""
        from app.models.user_settings import UIPreferences
        
        preferences = [
            {
                "preference_key": "default_theme",
                "preference_name": "Default Theme",
                "category": "appearance",
                "default_value": "system",
                "allowed_values": ["light", "dark", "system", "auto"],
                "value_type": "string",
                "description": "Default theme for new users"
            },
            {
                "preference_key": "default_page_size",
                "preference_name": "Default Page Size",
                "category": "pagination",
                "default_value": 20,
                "value_type": "integer",
                "min_value": 5,
                "max_value": 100,
                "description": "Default number of items per page"
            },
            {
                "preference_key": "enable_notifications",
                "preference_name": "Enable Notifications",
                "category": "notifications",
                "default_value": True,
                "value_type": "boolean",
                "description": "Enable browser notifications"
            },
            {
                "preference_key": "session_timeout",
                "preference_name": "Session Timeout",
                "category": "security",
                "default_value": 480,
                "value_type": "integer",
                "min_value": 30,
                "max_value": 1440,
                "description": "Session timeout in minutes",
                "requires_admin": True
            }
        ]
        
        for pref_data in preferences:
            preference = UIPreferences(
                preference_key=pref_data["preference_key"],
                preference_name=pref_data["preference_name"],
                category=pref_data["category"],
                default_value=pref_data["default_value"],
                allowed_values=pref_data.get("allowed_values"),
                value_type=pref_data["value_type"],
                description=pref_data.get("description"),
                is_user_configurable=not pref_data.get("requires_admin", False),
                requires_admin=pref_data.get("requires_admin", False),
                min_value=pref_data.get("min_value"),
                max_value=pref_data.get("max_value")
            )
            
            db.add(preference)
        
        await db.commit()
        self.logger.info("[OK] Seeded UI preferences")

    async def _seed_configuration_settings(self, db: AsyncSession):
        """Seed system configuration settings."""
        from app.models.configuration import Configuration, ConfigType
        
        configurations = [
            {
                "key": "system_name",
                "value": "ISP Billing System",
                "config_type": ConfigType.STRING,
                "category": "system",
                "description": "System name displayed in UI"
            },
            {
                "key": "company_name",
                "value": "Demo ISP Company",
                "config_type": ConfigType.STRING,
                "category": "company",
                "description": "Company name for branding"
            },
            {
                "key": "support_email",
                "value": "support@demoisp.co.ke",
                "config_type": ConfigType.STRING,
                "category": "contact",
                "description": "Support email address"
            },
            {
                "key": "mpesa_paybill",
                "value": "123456",
                "config_type": ConfigType.STRING,
                "category": "payment",
                "description": "MPESA Paybill number"
            },
            {
                "key": "default_currency",
                "value": "KES",
                "config_type": ConfigType.STRING,
                "category": "billing",
                "description": "Default currency for billing"
            },
            {
                "key": "max_login_attempts",
                "value": 5,
                "config_type": ConfigType.INTEGER,
                "category": "security",
                "description": "Maximum login attempts before lockout"
            },
            {
                "key": "enable_registration",
                "value": True,
                "config_type": ConfigType.BOOLEAN,
                "category": "system",
                "description": "Allow new user registration"
            }
        ]
        
        for config_data in configurations:
            config = Configuration(
                key=config_data["key"],
                value=str(config_data["value"]),
                config_type=config_data["config_type"],
                category=config_data["category"],
                description=config_data["description"],
                is_encrypted=False,
                is_sensitive=config_data["category"] == "security",
                is_active=True
            )
            
            db.add(config)
        
        await db.commit()
        self.logger.info("[OK] Seeded configuration settings")

    async def clear_all_data(self):
        """Clear all data from the database."""
        self.logger.warning("[TRASH]  CLEARING ALL DATA FROM DATABASE")

        try:
            # Import all seed functions and call their clear methods
            # Clear in reverse dependency order
            await seed_subscriptions(count=0, clear_existing=True)
            await seed_routers(count=0, clear_existing=True)
            await seed_plans(count=0, clear_existing=True)
            await seed_package_templates(count=0, clear_existing=True)
            await seed_package_categories(clear_existing=True)
            await seed_licences(count=0, clear_existing=True)
            await seed_users(count=0, clear_existing=True)

            # Clear organization data
            async with AsyncSessionLocal() as db:
                from sqlalchemy import delete
                from app.models.organization import OrganizationSettings, Organization
                from app.models.platform_billing import (
                    EarningsRecord, PlatformPayment, PlatformInvoice, PlatformSubscriptionTier
                )

                await db.execute(delete(EarningsRecord))
                await db.execute(delete(PlatformPayment))
                await db.execute(delete(PlatformInvoice))
                await db.execute(delete(OrganizationSettings))
                await db.execute(delete(Organization))
                await db.execute(delete(PlatformSubscriptionTier))
                await db.commit()

            # Clear additional system data
            async with AsyncSessionLocal() as db:
                from sqlalchemy import delete
                from app.models.notification import NotificationTemplate
                from app.models.user_settings import UIPreferences
                from app.models.configuration import Configuration

                await db.execute(delete(NotificationTemplate))
                await db.execute(delete(UIPreferences))
                await db.execute(delete(Configuration))
                await db.commit()

            self.logger.info("[OK] All data cleared successfully")

        except Exception as e:
            self.logger.error(f"[FAIL] Failed to clear data: {e}")
            raise

    def print_summary(self, results: Dict[str, Any]):
        """Print seeding summary."""
        print("\n" + "=" * 80)
        print("[DONE] SEEDING SUMMARY")
        print("=" * 80)
        
        if results["status"] == "completed":
            print(f"[OK] Status: {results['status'].upper()}")
            print(f"[CHART] Total Records: {results['total_records']}")
            print(f"[OK] Successful Models: {results['successful_models']}")
            print(f"[FAIL] Failed Models: {results['failed_models']}")
            print(f"[TIME]️  Duration: {results['duration_seconds']:.2f} seconds")
            
            print("\n[LIST] DETAILED RESULTS:")
            for model, result in results["results"].items():
                status_icon = "[OK]" if result["status"] == "success" else "[FAIL]"
                print(f"  {status_icon} {model.title()}: {result['count']} records")
                if result["status"] == "failed":
                    print(f"     Error: {result.get('error', 'Unknown error')}")
        else:
            print(f"[FAIL] Status: {results['status'].upper()}")
            print(f"[ERROR] Error: {results.get('error', 'Unknown error')}")
        
        print("\n[GO] NEXT STEPS:")
        print("  1. Start the FastAPI server: uvicorn app.main:app --reload")
        print("  2. Access API docs: http://localhost:8000/docs")
        print("  3. Login with credentials:")
        print("     * Platform Owner: platformadmin / admin123")
        print("     * ISP Admin (Demo ISP): demoispadmin / admin123")
        print("     * ISP Technician: demoistech1 / tech123")
        print("     * Customer: [customer username] / customer123")
        print("  4. Explore the seeded data through the API endpoints")
        
        print("\n[DATA] SEEDED DATA INCLUDES:")
        print("  * Platform subscription tiers (Hotspot & PPPoE)")
        print("  * Demo organizations (ISP providers)")
        print("  * Platform owner (super admin)")
        print("  * ISP admins and technicians per organization")
        print("  * Customer users across organizations")
        print("  * Realistic ISP service plans and pricing")
        print("  * MikroTik routers with devices and logs")
        print("  * Centipid licences with payment history")
        print("  * Customer subscriptions with billing data")
        print("  * Package templates and categories")
        print("  * Notification templates")
        print("  * System configuration settings")
        
        print("=" * 80)


async def main():
    """Main function with command line argument parsing."""
    parser = argparse.ArgumentParser(description="ISP Billing System - Master Data Seeder")
    
    parser.add_argument("--clear", action="store_true", help="Clear existing data before seeding")
    parser.add_argument("--users", type=int, default=50, help="Number of users to seed (default: 50)")
    parser.add_argument("--plans", type=int, default=20, help="Number of plans to seed (default: 20)")
    parser.add_argument("--routers", type=int, default=10, help="Number of routers to seed (default: 10)")
    parser.add_argument("--licences", type=int, default=5, help="Number of licences to seed (default: 5)")
    parser.add_argument("--subscriptions", type=int, default=100, help="Number of subscriptions to seed (default: 100)")
    parser.add_argument("--package-templates", type=int, default=15, help="Number of package templates to seed (default: 15)")
    
    parser.add_argument("--skip", nargs="+", help="Models to skip",
                       choices=["platform_tiers", "organizations", "users", "plans", "routers", "licences", "subscriptions", "package_templates"])
    parser.add_argument("--only", nargs="+", help="Only seed these models",
                       choices=["platform_tiers", "organizations", "users", "plans", "routers", "licences", "subscriptions", "package_templates"])
    
    parser.add_argument("--clear-only", action="store_true", help="Only clear data, don't seed")
    parser.add_argument("--quiet", action="store_true", help="Reduce output verbosity")
    
    args = parser.parse_args()
    
    # Configure logging
    if args.quiet:
        import logging
        logging.getLogger().setLevel(logging.WARNING)
    
    seeder = MasterSeeder()
    
    try:
        if args.clear_only:
            await seeder.clear_all_data()
            print("[OK] All data cleared successfully")
            return
        
        # Prepare counts
        counts = {
            "users": args.users,
            "plans": args.plans,
            "routers": args.routers,
            "licences": args.licences,
            "subscriptions": args.subscriptions,
            "package_templates": getattr(args, 'package_templates', 15)
        }
        
        # Run seeding
        results = await seeder.seed_all(
            clear_existing=args.clear,
            counts=counts,
            skip_models=args.skip,
            only_models=args.only
        )
        
        # Print summary
        if not args.quiet:
            seeder.print_summary(results)
        
        # Exit with appropriate code
        if results["status"] == "completed" and results["failed_models"] == 0:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Seeding interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERROR] Seeding failed: {e}")
        sys.exit(1)


# Convenience functions for programmatic use
async def seed_demo_data(clear_existing: bool = True) -> Dict[str, Any]:
    """Seed demo data with default settings."""
    seeder = MasterSeeder()
    return await seeder.seed_all(clear_existing=clear_existing)


async def seed_minimal_data(clear_existing: bool = True) -> Dict[str, Any]:
    """Seed minimal data for development."""
    seeder = MasterSeeder()
    return await seeder.seed_all(
        clear_existing=clear_existing,
        counts={
            "users": 10,
            "plans": 5,
            "routers": 3,
            "licences": 2,
            "subscriptions": 20,
            "package_templates": 5
        }
    )


async def seed_large_dataset(clear_existing: bool = False) -> Dict[str, Any]:
    """Seed large dataset for testing."""
    seeder = MasterSeeder()
    return await seeder.seed_all(
        clear_existing=clear_existing,
        counts={
            "users": 500,
            "plans": 50,
            "routers": 25,
            "licences": 10,
            "subscriptions": 1000,
            "package_templates": 30
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
