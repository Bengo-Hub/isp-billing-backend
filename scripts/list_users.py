"""List all users in the database."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.username, User.email, User.role, User.organization_id)
            .order_by(User.created_at)
        )
        users = result.all()
        print(f'\nTotal users: {len(users)}')
        print('\nUsers in database:')
        print('-' * 80)
        for user in users:
            org_id = user.organization_id or 'None'
            print(f'  {user.username:20} | {user.email:30} | {user.role:15} | Org: {org_id}')
        print('-' * 80)

if __name__ == '__main__':
    asyncio.run(main())
