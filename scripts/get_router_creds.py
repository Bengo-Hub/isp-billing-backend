"""Get router credentials from database."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.router import Router

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Router).where(Router.name == 'MikroTik1')
        )
        router = result.scalar_one_or_none()
        if router:
            print(f'Router: {router.name}')
            print(f'IP: {router.ip_address}')
            print(f'API Username: {router.username}')
            print(f'API Password: [{router.password}]')
            print(f'Port: {router.port}')
        else:
            print('Router not found')

if __name__ == "__main__":
    asyncio.run(main())
