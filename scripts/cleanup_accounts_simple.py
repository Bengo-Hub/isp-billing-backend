"""Clean up redundant accounts - simple approach using raw SQL."""

import asyncio
import sys
from pathlib import Path

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env  # This sets up the environment variables

from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)


async def cleanup_accounts():
    """Keep only superuser and demo accounts, remove others."""
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print("ACCOUNT CLEANUP - Keeping only superuser and demo")
        print("=" * 80)

        # Users to keep: superuser (9), demo (10)
        # Users to delete: codevertexadmin (12), platformadmin (6), admin (11)

        print("\n[STEP 1] Transfer ownership of all data to demo account...")

        # Transfer SMS credit accounts created_by
        result = await db.execute(
            text("UPDATE sms_credit_accounts SET created_by = 10 WHERE created_by IN (6, 11, 12)")
        )
        print(f"  - Updated {result.rowcount} SMS credit accounts")

        # Transfer SMS top-ups requested_by and approved_by
        result = await db.execute(
            text("UPDATE sms_top_ups SET requested_by = 10 WHERE requested_by IN (6, 11, 12)")
        )
        print(f"  - Updated {result.rowcount} SMS top-ups (requested_by)")

        result = await db.execute(
            text("UPDATE sms_top_ups SET approved_by = 10 WHERE approved_by IN (6, 11, 12)")
        )
        print(f"  - Updated {result.rowcount} SMS top-ups (approved_by)")

        # Transfer notification templates created_by
        result = await db.execute(
            text("UPDATE notification_templates SET created_by = 10 WHERE created_by IN (6, 11, 12)")
        )
        print(f"  - Updated {result.rowcount} notification templates")

        print("\n[STEP 2] Delete user settings...")
        result = await db.execute(
            text("DELETE FROM user_settings WHERE user_id IN (6, 11, 12)")
        )
        print(f"  - Deleted {result.rowcount} user settings")

        print("\n[STEP 3] Delete redundant users...")
        result = await db.execute(
            text("DELETE FROM users WHERE id IN (6, 11, 12)")
        )
        print(f"  - Deleted {result.rowcount} users")

        await db.commit()

        print("\n" + "=" * 80)
        print("[SUCCESS] CLEANUP COMPLETE")
        print("=" * 80)

        # Show remaining users
        result = await db.execute(
            text("SELECT username, email, organization_id FROM users ORDER BY id")
        )
        remaining_users = result.fetchall()

        print("\n[REMAINING ACCOUNTS]")
        print("-" * 80)
        for row in remaining_users:
            org_info = f"Org ID: {row[2]}" if row[2] else "Platform Owner"
            print(f"  {row[0]:20} | {row[1]:40} | {org_info}")

        # Show organizations
        result = await db.execute(
            text("SELECT name, slug, subscription_tier_id FROM organizations ORDER BY id")
        )
        orgs = result.fetchall()

        print("\n[ORGANIZATIONS]")
        print("-" * 80)
        for row in orgs:
            org_type = "Platform Org" if row[2] is None else f"ISP Org (Tier {row[2]})"
            print(f"  {row[0]:30} | Slug: {row[1]:20} | {org_type}")

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
