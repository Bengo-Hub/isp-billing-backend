"""Master seed script for seeding all demo data with configurable options.

Supports environment-aware seeding:
  --env dev         (default) Seeds everything including demo data
  --env production  Seeds only essential system data (RBAC, superuser, platform
                    org, platform settings, subscription tiers, notification
                    templates, system configurations)
"""

import asyncio
import argparse
import os
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
# Note: Organizations are seeded via scripts/add_default_org.py
from seed_rbac import seed_rbac
from seed_users import seed_users
from seed_plans import seed_plans, seed_package_templates, seed_package_categories
# from seed_routers import seed_routers  # Disabled - routers created during provisioning
from seed_licences import seed_licences
from seed_subscriptions import seed_subscriptions

logger = get_logger(__name__)

# Models that are only seeded in dev (demo data)
DEMO_ONLY_MODELS = {"users", "licences", "subscriptions"}


class MasterSeeder:
    """Master seeder for all system data with multi-tenancy support."""

    def __init__(self):
        self.logger = get_logger(__name__)

        # Default seed counts
        self.default_counts = {
            "users": 50,
            "plans": 10,
            "package_templates": 15,
            # "routers": 10,  # Disabled - routers created during provisioning
            "licences": 5,
            "subscriptions": 50
        }

        # Seed order (important for foreign key dependencies)
        # Organizations must be created FIRST via scripts/add_default_org.py
        # Routers are NOT seeded - they are created during provisioning
        self.seed_order = [
            "rbac",                # Roles & permissions
            "users",               # Platform owner, ISP admins, technicians, customers
            "licences",
            "package_categories",
            "package_templates",
            "plans",
            # "routers",           # Disabled - routers created during provisioning
            "subscriptions"
        ]

    async def seed_all(
        self,
        clear_existing: bool = False,
        counts: Dict[str, int] = None,
        skip_models: list = None,
        only_models: list = None,
        environment: str = "dev",
    ) -> Dict[str, Any]:
        """Seed all data with configurable options.

        Args:
            environment: "dev" seeds everything (demo data included).
                         "production" seeds only essential system data
                         (RBAC, platform admin, plans, templates, configs).
        """
        start_time = datetime.utcnow()
        is_production = environment == "production"

        # Use provided counts or defaults
        seed_counts = {**self.default_counts, **(counts or {})}
        skip_models = skip_models or []

        # In production mode, skip demo-only models
        if is_production:
            skip_models = list(set(skip_models) | DEMO_ONLY_MODELS)
            self.logger.info(
                f"[PROD] Production mode — skipping demo models: "
                f"{', '.join(sorted(DEMO_ONLY_MODELS))}"
            )

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
                # Try normal import first (module may be available on PATH)
                from ensure_billingcycle_values import ensure_billingcycle_values
            except Exception:
                # Fallback: attempt to load the utility from scripts/tools if present
                try:
                    import importlib.util
                    from pathlib import Path
                    tools_path = Path(__file__).parent / 'tools' / 'ensure_billingcycle_values.py'
                    if tools_path.exists():
                        spec = importlib.util.spec_from_file_location('ensure_billingcycle_values', str(tools_path))
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        ensure_billingcycle_values = getattr(mod, 'ensure_billingcycle_values')
                    else:
                        raise
                except Exception:
                    self.logger.exception("Failed to ensure billing cycle enum values, continuing")
            else:
                try:
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
            # In production, seed essentials (superuser, platform org, settings)
            # BEFORE other models so that created_by FKs have a valid user
            if is_production:
                await self._seed_production_essentials()

            # Seed each model in order
            for model_name in models_to_seed:
                self.logger.info(f"[SEED] Seeding {model_name}...")

                try:
                    if model_name == "rbac":
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
                            clear_existing=clear_existing,
                            demo_mode=True  # Create 4 demo packages (3 hotspot, 1 PPPoE)
                        )
                        results["plans"] = {"count": len(result), "status": "success"}

                    # elif model_name == "routers":
                    #     # Disabled - routers are created during provisioning
                    #     result = await seed_routers(
                    #         count=seed_counts["routers"],
                    #         clear_existing=clear_existing
                    #     )
                    #     results["routers"] = {"count": len(result), "status": "success"}

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
        """Clear system-level data that must be removed before deleting users.

        Dynamically discovers ALL tables with foreign keys to ``users`` and
        deletes their rows.  Each table is cleared in its own savepoint so
        that a missing table (older schema) doesn't abort the transaction.
        """
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text

            # Dynamically find every table that has a FK pointing at 'users'
            result = await db.execute(text("""
                SELECT DISTINCT tc.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND ccu.table_name = 'users'
                ORDER BY tc.table_name
            """))
            fk_tables = [row[0] for row in result.fetchall()]

            # Also include platform_settings explicitly (safety net)
            if "platform_settings" not in fk_tables:
                fk_tables.append("platform_settings")

            self.logger.info(
                f"Found {len(fk_tables)} tables referencing users: "
                f"{', '.join(fk_tables)}"
            )

            for table in fk_tables:
                try:
                    # Use savepoint so a failure doesn't abort the transaction
                    nested = await db.begin_nested()
                    await db.execute(text(f'DELETE FROM "{table}"'))
                    await nested.commit()
                except Exception:
                    await nested.rollback()

            await db.commit()
            self.logger.info(
                "Cleared system-level data (all tables referencing users)"
            )

    async def _seed_production_essentials(self):
        """Seed production-essential data: superuser, platform org, platform settings.

        This runs the same idempotent logic from seed_service.py so that
        ``python seed_all.py --env production`` produces a fully usable
        production database without any demo data.
        """
        from app.core.seed_service import (
            _seed_rbac,
            _seed_platform_admin,
            _seed_platform_settings,
            _seed_subscription_tiers,
        )

        async with AsyncSessionLocal() as db:
            try:
                roles = await _seed_rbac(db)
                admin = await _seed_platform_admin(db, roles)
                await _seed_platform_settings(db, admin)
                await _seed_subscription_tiers(db)

                # Ensure platform org (Codevertex IT Solutions) exists
                await self._seed_platform_org(db)

                await db.commit()
                self.logger.info("[OK] Production essentials seeded (superuser, platform org, settings, tiers)")
            except Exception as e:
                await db.rollback()
                self.logger.error(f"[FAIL] Failed to seed production essentials: {e}")
                raise

    async def _seed_platform_org(self, db: AsyncSession):
        """Ensure the platform organization (Codevertex IT Solutions) exists."""
        from app.models.organization import Organization, OrganizationType, OrganizationStatus

        result = await db.execute(
            select(Organization).where(Organization.slug == "codevertex")
        )
        if result.scalar_one_or_none():
            return

        self.logger.info("Creating platform organization: Codevertex IT Solutions")
        org = Organization(
            name="Codevertex IT Solutions",
            slug="codevertex",
            organization_type=OrganizationType.HOTSPOT,
            status=OrganizationStatus.ACTIVE,
            email="info@codevertexitsolutions.com",
            phone="+254792548766",
            address="OGINGA STREET, BANK ST., PIONEER HSE",
            city="KISUMU",
            country="Kenya",
            max_users=10,
            max_routers=0,
            max_customers=0,
        )
        db.add(org)
        await db.flush()
        self.logger.info(f"Platform organization created (id={org.id})")

    async def _seed_system_data(self):
        """Seed additional system data."""
        async with AsyncSessionLocal() as db:
            # Seed notification templates
            await self._seed_notification_templates(db)

            # Seed UI preferences
            await self._seed_ui_preferences(db)

            # Seed configuration settings
            await self._seed_configuration_settings(db)

            # NOTE: SMS messages, tickets, IP bindings, payments, expenses, vouchers,
            # and campaigns are NOT seeded - only demo users should be created via seed_demo_users.py

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
            # SMS Templates (updated with @ prefix and new variables)
            {
                "name": "subscription_success",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Dear @username, you have successfully subscribed to @package_name. Your subscription will expire on @expiry_date. Your username is @username and password is @password.",
                "hotspot_template": "Dear @username, you have successfully subscribed to @package_name. Expires: @expiry_date. Username: @username, Password: @password. To login visit @portal_url/buy/@org_slug and click connect.",
                "pppoe_template": "Hello @first_name, Your PPPoE account has been created. You can use account number: @account_number to pay. Login to your account at @portal_url/portal/pppoe/@org_slug/login using username: @username and password: @password",
                "description": "Sent when a customer successfully subscribes to a plan",
                "category": "subscription",
                "variables": json.dumps(["username", "package_name", "expiry_date", "password", "portal_url", "org_slug", "account_number", "first_name"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "subscription_expiry_reminder",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Hi @username, your @package_name subscription expires on @expiry_date. Renew now to continue enjoying uninterrupted service.",
                "hotspot_template": "Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",
                "pppoe_template": "Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",
                "description": "Sent to remind customers before their subscription expires",
                "category": "subscription",
                "variables": json.dumps(["username", "package_name", "expiry_date", "portal_url", "days_left", "paybill", "account_number"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "subscription_expired",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Dear @username, your @package_name subscription has expired. Renew now at @portal_url to restore your internet access.",
                "hotspot_template": "Dear @username, your package has expired. Kindly select another package to continue using the internet.",
                "pppoe_template": "Dear @username, your package has expired. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",
                "description": "Sent when a customer's subscription expires",
                "category": "subscription",
                "variables": json.dumps(["username", "package_name", "portal_url", "paybill", "account_number"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "payment_received",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Payment of @currency @amount received. Transaction ID: @transaction_id. Thank you for your payment!",
                "hotspot_template": "Payment of @currency @amount received for @package_name. Your hotspot is now active. Enjoy browsing!",
                "pppoe_template": "Payment of @currency @amount received for @package_name. Your PPPoE subscription has been activated.",
                "description": "Sent when a payment is successfully processed",
                "category": "billing",
                "variables": json.dumps(["currency", "amount", "transaction_id", "package_name"]),
                "user_type_specific": True,
                "is_active": True
            },
            {
                "name": "welcome_sms",
                "notification_type": NotificationType.SMS,
                "subject_template": None,
                "body_template": "Welcome to @company_name! Your account has been created. Username: @username. Visit @portal_url to manage your subscription.",
                "hotspot_template": "Welcome to @company_name! Connect to our WiFi hotspot and use username: @username to login at @portal_url/buy/@org_slug.",
                "pppoe_template": "Welcome to @company_name! Your PPPoE account is ready. Username: @username. Login at @portal_url/portal/pppoe/@org_slug/login. Contact support if you need help.",
                "description": "Sent when a new customer account is created",
                "category": "welcome",
                "variables": json.dumps(["company_name", "username", "portal_url", "org_slug"]),
                "user_type_specific": True,
                "is_active": True
            },
        ]

        # use module-level `select` (avoid local import which causes UnboundLocalError)

        for template_data in templates:
            # Skip if a template with the same name already exists (idempotent)
            existing = await db.execute(
                select(NotificationTemplate).where(NotificationTemplate.name == template_data["name"])
            )
            if existing.scalar_one_or_none():
                self.logger.debug(f"Notification template exists, skipping: {template_data['name']}")
                continue

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
        
        from sqlalchemy import select

        for pref_data in preferences:
            # Skip if preference already exists (idempotent)
            existing = await db.execute(
                select(UIPreferences).where(UIPreferences.preference_key == pref_data["preference_key"])
            )
            if existing.scalar_one_or_none():
                self.logger.debug(f"UI preference exists, skipping: {pref_data['preference_key']}")
                continue

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
            # await seed_routers(count=0, clear_existing=True)  # Disabled - routers created during provisioning
            await seed_plans(count=0, clear_existing=True, demo_mode=False)
            await seed_package_templates(count=0, clear_existing=True)
            await seed_package_categories(clear_existing=True)
            await seed_licences(count=0, clear_existing=True)
            await seed_users(count=0, clear_existing=True)

            # Clear routers (must be cleared before organizations since they have org FK)
            async with AsyncSessionLocal() as db:
                from sqlalchemy import delete
                from app.models.router import Router

                await db.execute(delete(Router))
                await db.commit()
                self.logger.info("[OK] Cleared all routers from database")

            # Clear organization data
            async with AsyncSessionLocal() as db:
                from sqlalchemy import delete
                from app.models.organization import OrganizationSettings, Organization
                from app.models.platform_billing import (
                    EarningsRecord, PlatformPayment, PlatformInvoice, PlatformSubscriptionTier
                )
                from app.models.payment_gateway import PayoutConfig

                await db.execute(delete(EarningsRecord))
                await db.execute(delete(PlatformPayment))
                await db.execute(delete(PlatformInvoice))
                await db.execute(delete(PayoutConfig))  # Delete payout configs before organizations
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
                from app.models.sms_credit import SMSTransaction, SMSCreditAccount, SMSTopUp

                await db.execute(delete(SMSTransaction))
                await db.execute(delete(SMSTopUp))
                await db.execute(delete(SMSCreditAccount))
                await db.execute(delete(NotificationTemplate))
                await db.execute(delete(UIPreferences))
                await db.execute(delete(Configuration))
                await db.commit()

            self.logger.info("[OK] All data cleared successfully")

        except Exception as e:
            self.logger.error(f"[FAIL] Failed to clear data: {e}")
            raise

    def print_summary(self, results: Dict[str, Any], environment: str = "dev"):
        """Print seeding summary."""
        print("\n" + "=" * 80)
        print("[DONE] SEEDING SUMMARY")
        print("=" * 80)
        print(f"[ENV] Environment: {environment.upper()}")

        if results["status"] == "completed":
            print(f"[OK] Status: {results['status'].upper()}")
            print(f"[CHART] Total Records: {results['total_records']}")
            print(f"[OK] Successful Models: {results['successful_models']}")
            print(f"[FAIL] Failed Models: {results['failed_models']}")
            print(f"[TIME]  Duration: {results['duration_seconds']:.2f} seconds")

            print("\n[LIST] DETAILED RESULTS:")
            for model, result in results["results"].items():
                status_icon = "[OK]" if result["status"] == "success" else "[FAIL]"
                print(f"  {status_icon} {model.title()}: {result['count']} records")
                if result["status"] == "failed":
                    print(f"     Error: {result.get('error', 'Unknown error')}")
        else:
            print(f"[FAIL] Status: {results['status'].upper()}")
            print(f"[ERROR] Error: {results.get('error', 'Unknown error')}")

        if environment == "production":
            print("\n[DATA] PRODUCTION DATA SEEDED:")
            print("  * RBAC roles and permissions")
            print("  * Platform superuser (credentials from env vars)")
            print("  * Platform organization (Codevertex IT Solutions)")
            print("  * Platform settings")
            print("  * Subscription tiers (Hotspot Starter, PPPoE Starter)")
            print("  * Package categories and templates")
            print("  * Plans (service packages)")
            print("  * Notification templates")
            print("  * System configuration settings")
            print("\n  NOTE: No demo users, licences, or subscriptions seeded in production")
        else:
            print("\n[GO] NEXT STEPS:")
            print("  1. Start the FastAPI server: uvicorn app.main:app --reload")
            print("  2. Access API docs: http://localhost:8000/docs")
            print("  3. Login with credentials:")
            print("     * Platform Owner: platformadmin / admin123")
            print("     * ISP Admin (Codevertex): codevertexadmin / admin123")
            print("     * ISP Technician: codevertextech1 / tech123")
            print("     * Customer: [customer username] / customer123")
            print("  4. Explore the seeded data through the API endpoints")

            print("\n[DATA] DEV DATA SEEDED:")
            print("  * Organization (created via scripts/add_default_org.py)")
            print("  * RBAC roles and permissions")
            print("  * Platform owner (super admin)")
            print("  * ISP admins and technicians")
            print("  * Customer users")
            print("  * Realistic ISP service plans and pricing")
            print("  * CodeVertex licences with payment history")
            print("  * Customer subscriptions with billing data")
            print("  * Package templates and categories")
            print("  * Notification templates (including SMS templates)")
            print("  * System configuration settings")
            print("\n  NOTE: MikroTik routers are NOT seeded - create them via provisioning")

        print("=" * 80)


async def main():
    """Main function with command line argument parsing."""
    parser = argparse.ArgumentParser(description="ISP Billing System - Master Data Seeder")
    
    parser.add_argument("--clear", action="store_true", help="Clear existing data before seeding")
    parser.add_argument(
        "--env",
        choices=["dev", "production"],
        default=os.getenv("ENVIRONMENT", "dev"),
        help="Environment mode: 'dev' seeds everything incl. demo data, "
             "'production' seeds only essential system data (default: $ENVIRONMENT or dev)",
    )
    parser.add_argument("--users", type=int, default=50, help="Number of users to seed (default: 50)")
    parser.add_argument("--plans", type=int, default=20, help="Number of plans to seed (default: 20)")
    # parser.add_argument("--routers", type=int, default=10, help="Number of routers to seed (default: 10)")  # Disabled
    parser.add_argument("--licences", type=int, default=5, help="Number of licences to seed (default: 5)")
    parser.add_argument("--subscriptions", type=int, default=100, help="Number of subscriptions to seed (default: 100)")
    parser.add_argument("--package-templates", type=int, default=15, help="Number of package templates to seed (default: 15)")

    parser.add_argument("--skip", nargs="+", help="Models to skip",
                       choices=["rbac", "users", "plans", "licences", "subscriptions", "package_categories", "package_templates"])
    parser.add_argument("--only", nargs="+", help="Only seed these models",
                       choices=["rbac", "users", "plans", "licences", "subscriptions", "package_categories", "package_templates"])

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
            await seeder._clear_system_level_data()
            await seeder.clear_all_data()
            print("[OK] All data cleared successfully")
            return
        
        # Prepare counts
        counts = {
            "users": args.users,
            "plans": args.plans,
            # "routers": args.routers,  # Disabled - routers created during provisioning
            "licences": args.licences,
            "subscriptions": args.subscriptions,
            "package_templates": getattr(args, 'package_templates', 15)
        }
        
        # Run seeding
        results = await seeder.seed_all(
            clear_existing=args.clear,
            counts=counts,
            skip_models=args.skip,
            only_models=args.only,
            environment=args.env,
        )
        
        # Print summary
        if not args.quiet:
            seeder.print_summary(results, environment=args.env)
        
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
    """Seed minimal data for development.

    Note: Routers are NOT seeded - create them via provisioning.
    """
    seeder = MasterSeeder()
    return await seeder.seed_all(
        clear_existing=clear_existing,
        counts={
            "users": 10,
            "plans": 5,
            # "routers": 3,  # Disabled - routers created during provisioning
            "licences": 2,
            "subscriptions": 20,
            "package_templates": 5
        }
    )


async def seed_large_dataset(clear_existing: bool = False) -> Dict[str, Any]:
    """Seed large dataset for testing.

    Note: Routers are NOT seeded - create them via provisioning.
    """
    seeder = MasterSeeder()
    return await seeder.seed_all(
        clear_existing=clear_existing,
        counts={
            "users": 500,
            "plans": 50,
            # "routers": 25,  # Disabled - routers created during provisioning
            "licences": 10,
            "subscriptions": 1000,
            "package_templates": 30
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
