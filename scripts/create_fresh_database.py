"""Create database schema from scratch using SQLAlchemy."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from app.core.database import Base
from app.core.config import settings

# Import all models to ensure they're registered with Base.metadata
from app.models import *  # noqa


async def create_database_schema():
    """Drop and recreate all database tables."""
    print("=" * 80)
    print("Creating Fresh Database Schema")
    print("=" * 80)

    print(f"\nDatabase: {settings.database_url}")
    print("\nWARNING: This will DROP ALL TABLES and recreate them!")

    # Create async engine
    engine = create_async_engine(
        settings.database_url,
        echo=True  # Show SQL statements
    )

    try:
        async with engine.begin() as conn:
            print("\n[1] Dropping all existing tables...")
            await conn.run_sync(Base.metadata.drop_all)
            print("[OK] All tables dropped")

            print("\n[2] Creating all tables from models...")
            await conn.run_sync(Base.metadata.create_all)
            print("[OK] All tables created")

        print("\n" + "=" * 80)
        print("[SUCCESS] Database schema created successfully!")
        print("=" * 80)
        print("\nNext steps:")
        print("  1. Run: python scripts/seed_demo_users.py")
        print("  2. Run: python scripts/seed_all.py")

    except Exception as e:
        print(f"\n[FAIL] Error creating schema: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_database_schema())
