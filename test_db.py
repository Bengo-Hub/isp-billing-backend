#!/usr/bin/env python3
"""Test database connection."""

import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine

# Set the database URL directly
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ispbilling"

async def test_connection():
    """Test database connection."""
    try:
        engine = create_async_engine(DATABASE_URL, echo=True)
        async with engine.begin() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT 1"))
            print("✅ Database connection successful!")
            print(f"Result: {result.scalar()}")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_connection())
