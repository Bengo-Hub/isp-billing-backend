import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.auth.service import AuthService

async def main():
    async with AsyncSessionLocal() as db:
        auth = AuthService(db)
        user = await auth.authenticate_user('demoispadmin', 'admin123')
        print('auth result:', user)

if __name__ == '__main__':
    asyncio.run(main())
