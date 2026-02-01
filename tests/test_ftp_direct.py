"""Direct FTP connection test to MikroTik router."""

import asyncio
import ftplib
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.models.router import Router, RouterStatus
from app.core.config import settings


async def test_ftp_connection():
    """Test direct FTP connection to router."""
    print("=" * 80)
    print("Direct FTP Connection Test")
    print("=" * 80)

    # Get database connection
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as session:
            # Get most recent provisioned router
            print("\n[1] Fetching router credentials from database...")
            result = await session.execute(
                select(Router)
                .where(Router.status == RouterStatus.ONLINE)
                .where(Router.organization_id.isnot(None))
                .order_by(Router.created_at.desc())
                .limit(1)
            )
            router = result.scalar_one_or_none()

            if not router:
                print("[FAIL] No provisioned routers found!")
                return

            print(f"[OK] Found router: {router.name}")
            print(f"  IP: {router.ip_address}")
            print(f"  Username: {router.username}")
            print(f"  Password: {'*' * len(router.password)}")

            # Test FTP connection
            print(f"\n[2] Testing FTP connection to {router.ip_address}:21...")
            print("-" * 80)

            ftp = None
            try:
                # Create FTP object
                print("\n  Step 1: Creating FTP object...")
                ftp = ftplib.FTP(timeout=30)
                print("  [OK] FTP object created")

                # Connect
                print(f"\n  Step 2: Connecting to {router.ip_address}:21...")
                response = ftp.connect(router.ip_address, 21)
                print(f"  [OK] Connected! Response: {response}")

                # Login
                print(f"\n  Step 3: Logging in as '{router.username}'...")
                response = ftp.login(router.username, router.password)
                print(f"  [OK] Logged in! Response: {response}")

                # Get welcome message
                print(f"\n  Step 4: Getting welcome message...")
                welcome = ftp.getwelcome()
                print(f"  Welcome: {welcome}")

                # List root directory
                print(f"\n  Step 5: Listing root directory...")
                files = ftp.nlst()
                print(f"  [OK] Found {len(files)} items in root directory:")
                for f in files[:10]:  # Show first 10
                    print(f"    - {f}")
                if len(files) > 10:
                    print(f"    ... and {len(files) - 10} more")

                # Check for hotspot directory
                print(f"\n  Step 6: Checking for /hotspot directory...")
                try:
                    ftp.cwd("hotspot")
                    print("  [OK] /hotspot directory exists")

                    # List hotspot files
                    hotspot_files = ftp.nlst()
                    print(f"  [OK] Found {len(hotspot_files)} files in /hotspot:")
                    for f in hotspot_files:
                        # Get file size
                        try:
                            size = ftp.size(f)
                            # Get modification time
                            try:
                                mdtm = ftp.sendcmd(f'MDTM {f}')
                                print(f"    - {f} ({size} bytes) - {mdtm}")
                            except:
                                print(f"    - {f} ({size} bytes)")
                        except:
                            print(f"    - {f}")

                except ftplib.error_perm as e:
                    print(f"  [FAIL] Cannot access /hotspot: {e}")

                # Success!
                print("\n" + "=" * 80)
                print("[SUCCESS] FTP connection and authentication working!")
                print("=" * 80)

            except ftplib.error_perm as e:
                print(f"\n[FAIL] FTP Permission Error: {e}")
                print("  This usually means wrong username/password")

            except ConnectionRefusedError as e:
                print(f"\n[FAIL] Connection Refused: {e}")
                print("  FTP service might not be running or is blocking connections")

            except OSError as e:
                print(f"\n[FAIL] OS Error: {e}")
                print(f"  Error code: {e.errno if hasattr(e, 'errno') else 'unknown'}")

            except Exception as e:
                print(f"\n[FAIL] Unexpected Error: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()

            finally:
                if ftp:
                    try:
                        ftp.quit()
                        print("\n[OK] FTP connection closed gracefully")
                    except:
                        try:
                            ftp.close()
                            print("\n[OK] FTP connection force closed")
                        except:
                            pass

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_ftp_connection())
