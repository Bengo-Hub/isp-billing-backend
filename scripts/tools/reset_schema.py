"""Reset the public schema (drop all objects) and recreate it cleanly."""
import asyncio
import sys
from pathlib import Path
from sqlalchemy import text

# Ensure backend dir is on path and .env is loaded like other scripts
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
from scripts.seed_env import setup_seed_environment
setup_seed_environment()

from app.core.database import engine

async def reset_schema():
    async with engine.begin() as conn:
        # Drop and recreate schema
        await conn.execute(text('DROP SCHEMA public CASCADE'))
        await conn.execute(text('CREATE SCHEMA public'))
        print('✓ Public schema reset')

if __name__ == '__main__':
    asyncio.run(reset_schema())
