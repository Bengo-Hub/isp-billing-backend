"""Check all routers in the database."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.models.router import Router
from app.core.config import settings


async def check_routers():
    """Query and display all routers in the database."""
    # Use the database URL from settings
    engine = create_async_engine(
        settings.database_url,
        echo=False
    )

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as session:
            result = await session.execute(
                select(Router).order_by(Router.created_at.desc())
            )
            routers = result.scalars().all()

            print(f'\n=== Found {len(routers)} routers in database ===\n')

            if not routers:
                print("No routers found in database!")
                return

            for router in routers:
                print(f'ID: {router.id}')
                print(f'Name: {router.name}')
                print(f'IP Address: {router.ip_address}')
                print(f'Status: {router.status}')
                print(f'Organization ID: {router.organization_id}')
                print(f'Username: {router.username}')
                print(f'Created: {router.created_at}')
                print(f'Updated: {router.updated_at}')
                print('-' * 50)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_routers())
