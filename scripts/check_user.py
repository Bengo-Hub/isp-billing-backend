import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env  # Ensure environment variables are set for DB connection

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == "demoispadmin"))
        user = result.scalar_one_or_none()
        if not user:
            print("NOT FOUND")
            return
        print("FOUND")
        print("id:", user.id)
        print("username:", user.username)
        print("email:", user.email)
        print("is_active:", user.is_active)
        print("role:", user.role)
        print("hashed_password:", user.hashed_password)

if __name__ == '__main__':
    asyncio.run(main())
