#!/usr/bin/env python3
"""Ensure billingcycle enum contains expected values."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings
from sqlalchemy import text

EXPECTED = ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY", "ONE_TIME"]

async def ensure_billingcycle_values():
    database_url = settings.database_url
    if not database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid WHERE t.typname = 'billingcycle' ORDER BY e.enumsortorder"))
        existing = [r[0] for r in res.fetchall()]
        print("Existing billingcycle values:", existing)
        for val in EXPECTED:
            if val not in existing:
                print(f"Adding enum value: {val}")
                try:
                    await conn.execute(text(f"ALTER TYPE billingcycle ADD VALUE '{val}';"))
                except Exception as e:
                    print(f"Failed to add {val}: {e}")
            else:
                print(f"Already present: {val}")


async def main():
    await ensure_billingcycle_values()

if __name__ == '__main__':
    asyncio.run(main())