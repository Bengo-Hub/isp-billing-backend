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
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger

# Import individual seed functions
from seed_users import seed_users
from seed_plans import seed_plans, seed_package_templates, seed_package_categories
from seed_routers import seed_routers
from seed_licences import seed_licences
from seed_subscriptions import seed_subscriptions

logger = get_logger(__name__)


class MasterSeeder:
    """Master seeder for all system data."""

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
        self.seed_order = [
            "users",
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
        self.logger.info("🌱 STARTING MASTER SEED PROCESS")
        self.logger.info("=" * 60)
        
        if clear_existing:
            self.logger.warning("⚠️  CLEARING ALL EXISTING DATA")
        
        self.logger.info(f"📋 Models to seed: {', '.join(models_to_seed)}")
        self.logger.info(f"📊 Seed counts: {seed_counts}")
        
        try:
            # Seed each model in order
            for model_name in models_to_seed:
                self.logger.info(f"🌱 Seeding {model_name}...")
                
                try:
                    if model_name == "users":
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
                    
                    self.logger.info(f"✅ {model_name} seeded successfully: {results[model_name]['count']} records")
                    
                    # Clear existing flag after first model to avoid clearing dependencies
                    clear_existing = False
                    
                except Exception as e:
                    self.logger.error(f"❌ Failed to seed {model_name}: {e}")
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
            self.logger.info("🎉 MASTER SEED PROCESS COMPLETED")
            self.logger.info("=" * 60)
            self.logger.info(f"📊 Total records created: {total_records}")
            self.logger.info(f"✅ Successful models: {successful_models}")
            self.logger.info(f"❌ Failed models: {failed_models}")
            self.logger.info(f"⏱️  Total duration: {duration:.2f} seconds")
            
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
            self.logger.error(f"💥 Master seed process failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "results": results,
                "completed_at": datetime.utcnow().isoformat()
            }

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
        from app.models.notification import NotificationTemplate
        
        templates = [
            {
                "name": "Welcome Email",
                "template_type": "email",
                "subject": "Welcome to {company_name}",
                "content": """
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
                "variables": ["company_name", "customer_name", "username", "plan_name", "download_speed"],
                "is_active": True
            },
            {
                "name": "Payment Confirmation SMS",
                "template_type": "sms",
                "subject": None,
                "content": "Payment confirmed! KES {amount} received for {plan_name}. Valid until {expiry_date}. Thank you!",
                "variables": ["amount", "plan_name", "expiry_date"],
                "is_active": True
            },
            {
                "name": "Service Expiry Reminder",
                "template_type": "sms",
                "subject": None,
                "content": "Hi {customer_name}, your {plan_name} expires on {expiry_date}. Renew now to avoid service interruption. Pay via MPESA: {paybill_number}",
                "variables": ["customer_name", "plan_name", "expiry_date", "paybill_number"],
                "is_active": True
            }
        ]
        
        for template_data in templates:
            template = NotificationTemplate(
                name=template_data["name"],
                template_type=template_data["template_type"],
                subject=template_data["subject"],
                content=template_data["content"],
                variables=template_data["variables"],
                is_active=template_data["is_active"],
                created_at=datetime.utcnow()
            )
            
            db.add(template)
        
        await db.commit()
        self.logger.info("✅ Seeded notification templates")

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
        self.logger.info("✅ Seeded UI preferences")

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
                value=config_data["value"],
                config_type=config_data["config_type"],
                category=config_data["category"],
                description=config_data["description"],
                is_encrypted=False,
                is_public=config_data["category"] in ["system", "company", "contact"]
            )
            
            db.add(config)
        
        await db.commit()
        self.logger.info("✅ Seeded configuration settings")

    async def clear_all_data(self):
        """Clear all data from the database."""
        self.logger.warning("🗑️  CLEARING ALL DATA FROM DATABASE")
        
        try:
            # Import all seed functions and call their clear methods
            await seed_subscriptions(count=0, clear_existing=True)
            await seed_routers(count=0, clear_existing=True)
            await seed_plans(count=0, clear_existing=True)
            await seed_package_templates(count=0, clear_existing=True)
            await seed_package_categories(clear_existing=True)
            await seed_licences(count=0, clear_existing=True)
            await seed_users(count=0, clear_existing=True)
            
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
            
            self.logger.info("✅ All data cleared successfully")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to clear data: {e}")
            raise

    def print_summary(self, results: Dict[str, Any]):
        """Print seeding summary."""
        print("\n" + "=" * 80)
        print("🎉 SEEDING SUMMARY")
        print("=" * 80)
        
        if results["status"] == "completed":
            print(f"✅ Status: {results['status'].upper()}")
            print(f"📊 Total Records: {results['total_records']}")
            print(f"✅ Successful Models: {results['successful_models']}")
            print(f"❌ Failed Models: {results['failed_models']}")
            print(f"⏱️  Duration: {results['duration_seconds']:.2f} seconds")
            
            print("\n📋 DETAILED RESULTS:")
            for model, result in results["results"].items():
                status_icon = "✅" if result["status"] == "success" else "❌"
                print(f"  {status_icon} {model.title()}: {result['count']} records")
                if result["status"] == "failed":
                    print(f"     Error: {result.get('error', 'Unknown error')}")
        else:
            print(f"❌ Status: {results['status'].upper()}")
            print(f"💥 Error: {results.get('error', 'Unknown error')}")
        
        print("\n🚀 NEXT STEPS:")
        print("  1. Start the FastAPI server: uvicorn app.main:app --reload")
        print("  2. Access API docs: http://localhost:8000/docs")
        print("  3. Login with admin credentials: admin / admin123")
        print("  4. Explore the seeded data through the API endpoints")
        
        print("\n📚 SEEDED DATA INCLUDES:")
        print("  • Admin, technician, and customer users")
        print("  • Realistic ISP service plans and pricing")
        print("  • MikroTik routers with devices and logs")
        print("  • Centipid licences with payment history")
        print("  • Customer subscriptions with billing data")
        print("  • Package templates and categories")
        print("  • Notification templates")
        print("  • System configuration settings")
        
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
                       choices=["users", "plans", "routers", "licences", "subscriptions", "package_templates"])
    parser.add_argument("--only", nargs="+", help="Only seed these models",
                       choices=["users", "plans", "routers", "licences", "subscriptions", "package_templates"])
    
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
            print("✅ All data cleared successfully")
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
        print(f"\n💥 Seeding failed: {e}")
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
