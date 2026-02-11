"""
Database schema verification script.
Run this to check if your database schema matches your models.
"""
import asyncio
from sqlalchemy import text
from app.core.database import engine, AsyncSessionLocal
from app.models.provisioning import ProvisioningSession


async def check_provisioning_table():
    """Check if provisioning_sessions table exists and has correct columns."""
    async with AsyncSessionLocal() as session:
        try:
            # Check if table exists
            result = await session.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'provisioning_sessions'
                ORDER BY ordinal_position;
            """))

            columns = result.fetchall()

            if not columns:
                print("❌ ERROR: provisioning_sessions table does not exist!")
                print("   Run: alembic upgrade head")
                return False

            print("✅ Table 'provisioning_sessions' exists")
            print("\nColumns:")
            for col in columns:
                print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")

            # Check if enum types exist
            result = await session.execute(text("""
                SELECT typname
                FROM pg_type
                WHERE typname IN ('provisioningstatus', 'provisioningstep', 'servicetype', 'provisioningpriority');
            """))

            enums = result.fetchall()
            print(f"\n✅ Found {len(enums)} enum types:")
            for enum in enums:
                print(f"  - {enum[0]}")

            if len(enums) < 4:
                print("⚠️  WARNING: Some enum types might be missing!")

            return True

        except Exception as e:
            print(f"❌ ERROR checking database schema: {e}")
            return False


async def check_active_sessions():
    """Check for any active/stuck provisioning sessions."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(text("""
                SELECT session_id, router_id, status, current_step, created_at, error_message
                FROM provisioning_sessions
                WHERE status IN ('PENDING', 'IN_PROGRESS')
                ORDER BY created_at DESC
                LIMIT 10;
            """))

            sessions = result.fetchall()

            if sessions:
                print(f"\n⚠️  Found {len(sessions)} active/pending sessions:")
                for s in sessions:
                    print(f"  - {s[0]}: router_id={s[1]}, status={s[2]}, step={s[3]}")
                    if s[5]:
                        print(f"    Error: {s[5]}")
            else:
                print("\n✅ No active/pending sessions found")

        except Exception as e:
            print(f"❌ ERROR checking active sessions: {e}")


async def main():
    print("=" * 60)
    print("DATABASE SCHEMA VERIFICATION")
    print("=" * 60)

    # Check table schema
    schema_ok = await check_provisioning_table()

    # Check for active sessions
    await check_active_sessions()

    print("\n" + "=" * 60)
    if schema_ok:
        print("✅ Schema check completed")
    else:
        print("❌ Schema issues found - run migrations!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
