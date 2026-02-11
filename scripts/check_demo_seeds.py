import asyncio
import sys
from pathlib import Path
# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.organization import Organization
from app.models.router import Router
from app.models.customer_portal import VoucherCode
from app.models.user import User

async def check():
    async with AsyncSessionLocal() as db:
        org = await db.scalar(select(Organization).where(Organization.slug == 'demo-isp'))
        print('Demo org exists:', bool(org))
        router = await db.scalar(select(Router).where(Router.name == 'MikroTik1'))
        print('Router:', getattr(router, 'ip_address', None), getattr(router, 'username', None))
        vouchers = await db.execute(select(VoucherCode).where(VoucherCode.organization_id == org.id)) if org else None
        print('Voucher count:', len(list(vouchers.scalars().all())) if vouchers else 0)
        u1 = await db.scalar(select(User).where(User.username == 'demo_hotspot'))
        u2 = await db.scalar(select(User).where(User.username == 'demo_pppoe'))
        print('Hotspot user exists:', bool(u1))
        print('PPPoE user exists:', bool(u2))

if __name__ == '__main__':
    asyncio.run(check())