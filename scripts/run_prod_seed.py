import asyncio
import sys
from pathlib import Path
import importlib.util

# Ensure backend dir is importable for package imports used by seed modules
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# locate seed_all by path and load it as a module
base = Path(__file__).parent
# Add the seeds directory to sys.path so seed_* helpers can import each other
seeds_dir = base / 'seeds'
sys.path.insert(0, str(seeds_dir))
seed_all_path = seeds_dir / 'seed_all.py'
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