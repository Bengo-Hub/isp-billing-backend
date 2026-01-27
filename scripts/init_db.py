#!/usr/bin/env python3
"""Initialize database with initial data."""

import asyncio
import sys
from pathlib import Path

# Ensure environment variables are loaded like other scripts
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
from scripts.seed_env import setup_seed_environment
setup_seed_environment()

from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings
from app.core.database import Base
# Import all models to ensure they are registered
from app.models import *
from app.core.security import get_password_hash


async def init_db():
    """Initialize database with tables and initial data."""
    # Ensure we're using asyncpg driver
    database_url = settings.database_url
    if not database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    
    # Create async engine
    engine = create_async_engine(database_url)
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    print("Database initialized successfully!")


if __name__ == "__main__":
    asyncio.run(init_db())
