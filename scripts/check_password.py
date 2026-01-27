import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import verify_password
from app.models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == 'demoispadmin'))
        user = result.scalar_one_or_none()
        if not user:
            print('User not found')
            return
        print('hashed:', user.hashed_password)
        ok = verify_password('admin123', user.hashed_password)
        print('verify admin123 ->', ok)
        ok2 = verify_password('wrongpass', user.hashed_password)
        print('verify wrongpass ->', ok2)

if __name__ == '__main__':
    asyncio.run(main())
