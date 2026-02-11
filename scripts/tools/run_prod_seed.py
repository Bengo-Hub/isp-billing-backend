import asyncio
import sys
from pathlib import Path
import importlib.util

# locate seed_all by path and load it as a module
base = Path(__file__).parent
seed_all_path = base / 'seeds' / 'seed_all.py'
spec = importlib.util.spec_from_file_location('seed_all', str(seed_all_path))
seed_all = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_all)

async def main():
    seeder = seed_all.MasterSeeder()
    print('Seeding production essentials (clear_existing=True)')
    res = await seeder.seed_all(clear_existing=True, environment='production')
    print('Seed result:', res)

if __name__ == '__main__':
    asyncio.run(main())