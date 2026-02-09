"""
Migration script to update notification templates for existing organizations.

This script updates all organization settings with the new template formats
that include @portal_url, @org_slug, @account_number, and @paybill variables.

Usage:
    python scripts/update_notification_templates.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.models.organization import OrganizationSettings


# New template values from the model defaults
NEW_TEMPLATES = {
    # SMS Templates
    "hotspot_payment_confirmation_sms": "Dear @username, you have successfully subscribed to @package_name. Your subscription will expire on @expiry_date. Your username is @username and password is @password. To login visit @portal_url/buy/@org_slug and click connect.",

    "pppoe_payment_confirmation_sms": "Hello @first_name, Your PPPoE account has been created. You can use account number: @account_number to pay. Login to your account at @portal_url/portal/pppoe/@org_slug/login using username: @username and password: @password",

    "hotspot_expiry_notification_sms": "Dear @username, your package has expired. Kindly select another package to continue using the internet.",

    "pppoe_expiry_notification_sms": "Dear @username, your package has expired. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",

    "hotspot_expiry_reminder_sms": "Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",

    "pppoe_expiry_reminder_sms": "Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.",

    # WhatsApp Templates
    "hotspot_payment_confirmation_whatsapp": "Hello @username! 👋\n\nYou've successfully subscribed to *@package_name*\n\n✅ Username: @username\n🔑 Password: @password\n📅 Expires: @expiry_date\n\n🌐 Login: @portal_url/buy/@org_slug\n(Click connect and login with your details)\n\nThank you for choosing us!",

    "pppoe_payment_confirmation_whatsapp": "Hello @first_name! 👋\n\nYour PPPoE account is ready!\n\n*@package_name*\n\n✅ Username: @username\n🔑 Password: @password\n📅 Expires: @expiry_date\n💳 Account Number: @account_number\n\n🌐 Login: @portal_url/portal/pppoe/@org_slug/login\n\nThank you for choosing us!",

    "hotspot_expiry_notification_whatsapp": "Hello @username! 📢\n\nYour internet package has expired. Please purchase a new package to continue browsing.\n\nThank you!",

    "pppoe_expiry_notification_whatsapp": "Hello @username! 📢\n\nYour internet subscription has expired.\n\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to continue browsing!",

    "hotspot_expiry_reminder_whatsapp": "Hello @username! ⏰\n\nYour package expires in *@days_left days*\n\n📅 Expiry Date: @expiry_date\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to avoid interruption!",

    "pppoe_expiry_reminder_whatsapp": "Hello @username! ⏰\n\nYour subscription expires in *@days_left days*\n\n📅 Expiry Date: @expiry_date\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to stay connected!",

    # Email Template
    "pppoe_email_reminder_subject": "Your subscription expires in @days_left days",
    "pppoe_email_reminder_message": "Dear @first_name,<br><br>Your internet subscription will expire in @days_left days on @expiry_date.<br><br>Please renew by paying to paybill @paybill using account number @account_number to avoid service interruption.<br><br>Kind regards,<br>@company_name",
}


async def update_templates():
    """Update notification templates for all existing organizations."""
    print("Starting template migration...")

    async with AsyncSessionLocal() as session:
        # Get all organization settings
        result = await session.execute(select(OrganizationSettings))
        settings = result.scalars().all()

        print(f"Found {len(settings)} organization settings to update")

        updated_count = 0
        for setting in settings:
            print(f"\nUpdating organization_id: {setting.organization_id}")

            # Update each template field
            for field_name, new_value in NEW_TEMPLATES.items():
                setattr(setting, field_name, new_value)
                print(f"  [OK] Updated {field_name}")

            updated_count += 1

        # Commit all changes
        await session.commit()
        print(f"\n[SUCCESS] Updated templates for {updated_count} organizations")


async def main():
    """Main entry point."""
    try:
        await update_templates()
        print("\n[DONE] Migration completed successfully!")
    except Exception as e:
        print(f"\n[ERROR] Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
