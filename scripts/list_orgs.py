"""List all organizations in the database."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.organization import Organization

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Organization.id, Organization.name, Organization.slug)
            .order_by(Organization.created_at)
        )
        orgs = result.all()
        print(f'\nTotal organizations: {len(orgs)}')
        print('\nOrganizations in database:')
        print('-' * 80)
        for org in orgs:
            print(f'  ID: {org.id} | {org.name:30} | Slug: {org.slug}')
        print('-' * 80)

if __name__ == '__main__':
    asyncio.run(main())
