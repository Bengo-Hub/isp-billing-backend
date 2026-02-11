"""Simple script runner for seeding operations."""

import asyncio
import sys
from pathlib import Path

# Add the backend directory to Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from seed_all import seed_demo_data, seed_minimal_data, seed_large_dataset, MasterSeeder


async def main():
    """Main function for running seed operations."""
    print("🌱 ISP Billing System - Data Seeder")
    print("=" * 50)
    print("Select seeding option:")
    print("1. Demo Data (Default - 50 users, 20 plans, 10 routers, etc.)")
    print("2. Minimal Data (10 users, 5 plans, 3 routers, etc.)")
    print("3. Large Dataset (500 users, 50 plans, 25 routers, etc.)")
    print("4. Clear All Data")
    print("5. Custom Seeding")
    print("0. Exit")
    
    choice = input("\nEnter your choice (1-5, 0 to exit): ").strip()
    
    try:
        if choice == "0":
            print("👋 Goodbye!")
            return
        
        elif choice == "1":
            print("\n🌱 Seeding demo data...")
            results = await seed_demo_data(clear_existing=True)
            
        elif choice == "2":
            print("\n🌱 Seeding minimal data...")
            results = await seed_minimal_data(clear_existing=True)
            
        elif choice == "3":
            print("\n🌱 Seeding large dataset...")
            confirm = input("⚠️  This will create a large amount of data. Continue? (y/N): ")
            if confirm.lower() != 'y':
                print("❌ Cancelled")
                return
            results = await seed_large_dataset(clear_existing=True)
            
        elif choice == "4":
            print("\n🗑️  Clearing all data...")
            confirm = input("⚠️  This will DELETE ALL DATA. Are you sure? (y/N): ")
            if confirm.lower() != 'y':
                print("❌ Cancelled")
                return
            
            seeder = MasterSeeder()
            await seeder.clear_all_data()
            print("✅ All data cleared successfully")
            return
            
        elif choice == "5":
            print("\n🔧 Custom seeding...")
            users = int(input("Number of users (default 50): ") or "50")
            plans = int(input("Number of plans (default 20): ") or "20")
            routers = int(input("Number of routers (default 10): ") or "10")
            subscriptions = int(input("Number of subscriptions (default 100): ") or "100")
            
            clear = input("Clear existing data? (y/N): ").lower() == 'y'
            
            seeder = MasterSeeder()
            results = await seeder.seed_all(
                clear_existing=clear,
                counts={
                    "users": users,
                    "plans": plans,
                    "routers": routers,
                    "subscriptions": subscriptions,
                    "licences": 5,
                    "package_templates": 15
                }
            )
            
        else:
            print("❌ Invalid choice")
            return
        
        # Print results if available
        if 'results' in locals():
            seeder = MasterSeeder()
            seeder.print_summary(results)
        
    except KeyboardInterrupt:
        print("\n🛑 Operation cancelled by user")
    except Exception as e:
        print(f"\n💥 Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
