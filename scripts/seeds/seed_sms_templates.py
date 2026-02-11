"""Seed SMS notification templates."""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import scripts.seed_env  # noqa: F401

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.notification import NotificationTemplate, NotificationType
from app.models.user import User


# SMS Template definitions
SMS_TEMPLATES = [
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
    },
    {
        "name": "welcome_message",
        "notification_type": NotificationType.SMS,
        "subject_template": None,
        "body_template": "Welcome to {company_name}! Your account has been created. Username: {username}. Visit {portal_url} to manage your subscription.",
        "hotspot_template": "Welcome to {company_name}! Connect to our WiFi hotspot and use username: {username} to login.",
        "pppoe_template": "Welcome to {company_name}! Your PPPoE account is ready. Username: {username}. Contact support if you need help setting up.",
        "description": "Sent when a new customer account is created",
        "category": "welcome",
        "variables": json.dumps(["company_name", "username", "portal_url"]),
        "user_type_specific": True,
    },
]


async def seed_sms_templates(clear_existing: bool = False) -> List[NotificationTemplate]:
    """Seed SMS notification templates."""
    async with AsyncSessionLocal() as db:
        try:
            # Get a system user to use as creator
            result = await db.execute(
                select(User).where(User.email == "platform@ispbilling.local").limit(1)
            )
            system_user = result.scalar_one_or_none()

            if not system_user:
                # Try to get any admin user
                result = await db.execute(
                    select(User).where(User.role == "platform_owner").limit(1)
                )
                system_user = result.scalar_one_or_none()

            if not system_user:
                # Get any user as fallback
                result = await db.execute(select(User).limit(1))
                system_user = result.scalar_one_or_none()

            if not system_user:
                print("No users found in database. Please run seed_users first.")
                return []

            creator_id = system_user.id

            if clear_existing:
                # Delete existing SMS templates
                result = await db.execute(
                    select(NotificationTemplate).where(
                        NotificationTemplate.notification_type == NotificationType.SMS
                    )
                )
                existing = result.scalars().all()
                for template in existing:
                    await db.delete(template)
                await db.commit()
                print(f"Cleared {len(existing)} existing SMS templates")

            created_templates = []

            for template_data in SMS_TEMPLATES:
                # Check if template already exists
                result = await db.execute(
                    select(NotificationTemplate).where(
                        NotificationTemplate.name == template_data["name"]
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    print(f"Template '{template_data['name']}' already exists, skipping...")
                    created_templates.append(existing)
                    continue

                # Create new template
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
                    is_active=True,
                    created_by=creator_id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )

                db.add(template)
                created_templates.append(template)
                print(f"Created SMS template: {template_data['name']}")

            await db.commit()
            print(f"\nSuccessfully seeded {len(created_templates)} SMS templates")
            return created_templates

        except Exception as e:
            await db.rollback()
            print(f"Error seeding SMS templates: {e}")
            raise


async def main():
    """Run the SMS template seeding."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed SMS notification templates")
    parser.add_argument("--clear", action="store_true", help="Clear existing SMS templates before seeding")
    args = parser.parse_args()

    print("Seeding SMS templates...")
    templates = await seed_sms_templates(clear_existing=args.clear)
    print(f"Done! Created {len(templates)} templates")


if __name__ == "__main__":
    asyncio.run(main())
