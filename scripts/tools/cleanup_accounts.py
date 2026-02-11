"""Clean up redundant accounts - keep only superuser and demo."""

import asyncio
import sys
from pathlib import Path

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env  # This sets up the environment variables

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.user import User
from app.models.user_settings import UserSettings
from app.models.organization import Organization
from app.models.sms_credit import SMSCreditAccount, SMSTopUp

logger = get_logger(__name__)


async def cleanup_accounts():
    """Keep only superuser and demo accounts, remove others."""
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print("ACCOUNT CLEANUP - Keeping only superuser and demo")
        print("=" * 80)

        # Get all users
        result = await db.execute(select(User))
        users = result.scalars().all()

        print("\n[CURRENT USERS]")
        for u in users:
            print(f"  - {u.username:20} | {u.email:40} | ID: {u.id}")

        # Users to keep
        keep_usernames = {'superuser', 'demo'}

        # Find users to delete
        users_to_delete = []
        for user in users:
            if user.username not in keep_usernames:
                users_to_delete.append(user)

        if not users_to_delete:
            print("\n[OK] No accounts to delete. Database is clean!")
            return

        print(f"\n[DELETE] Removing {len(users_to_delete)} redundant accounts:")
        for user in users_to_delete:
            print(f"  - {user.username} ({user.email})")

        # Delete cascading dependencies first (in correct order)
        user_ids = [u.id for u in users_to_delete]

        # 1. Get SMS credit accounts for these users
        result = await db.execute(
            select(SMSCreditAccount).where(SMSCreditAccount.created_by.in_(user_ids))
        )
        sms_accounts = result.scalars().all()
        sms_account_ids = [acc.id for acc in sms_accounts]

        if sms_account_ids:
            # 1a. Delete SMS top-ups first (foreign key to sms_credit_accounts)
            result = await db.execute(
                delete(SMSTopUp).where(SMSTopUp.account_id.in_(sms_account_ids))
            )
            print(f"\n  [OK] Deleted {result.rowcount} SMS top-ups")

            # 1b. Delete SMS Credit Accounts
            result = await db.execute(
                delete(SMSCreditAccount).where(SMSCreditAccount.created_by.in_(user_ids))
            )
            print(f"  [OK] Deleted {result.rowcount} SMS credit accounts")
        else:
            print(f"\n  [OK] No SMS data to delete")

        # 2. Delete User Settings
        result = await db.execute(
            delete(UserSettings).where(UserSettings.user_id.in_(user_ids))
        )
        print(f"  [OK] Deleted {result.rowcount} user settings")

        # Delete users
        result = await db.execute(
            delete(User).where(User.id.in_(user_ids))
        )
        print(f"  [OK] Deleted {result.rowcount} users")

        await db.commit()

        print("\n" + "=" * 80)
        print("[SUCCESS] CLEANUP COMPLETE")
        print("=" * 80)

        # Show remaining users
        result = await db.execute(select(User).order_by(User.id))
        remaining_users = result.scalars().all()

        print("\n[REMAINING ACCOUNTS]")
        print("-" * 80)
        for u in remaining_users:
            org_info = f"Org ID: {u.organization_id}" if u.organization_id else "Platform Owner"
            print(f"  {u.username:20} | {u.email:40} | {org_info}")

        # Show organizations
        print("\n[ORGANIZATIONS]")
        print("-" * 80)
        result = await db.execute(select(Organization).order_by(Organization.id))
        orgs = result.scalars().all()
        for org in orgs:
            org_type = "Platform Org" if org.subscription_tier_id is None else f"ISP Org (Tier {org.subscription_tier_id})"
            print(f"  {org.name:30} | Slug: {org.slug:20} | {org_type}")

        print("\n" + "=" * 80)
        print("[RECOMMENDED CREDENTIALS]")
        print("=" * 80)
        print("\n[1] Platform Owner (Full System Access):")
        print("  - Username: superuser")
        print("  - Email: superuser@codevertexitsolutions.com")
        print("  - Password: superuser123")
        print("\n[2] Demo ISP Company Admin:")
        print("  - Username: demo")
        print("  - Email: demo@codevertexitsolutions.com")
        print("  - Password: demo123")
        print("  - Organization: Demo ISP Company (Trial)")
        print("\n[NOTE] Both accounts support login with username OR email!")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(cleanup_accounts())
