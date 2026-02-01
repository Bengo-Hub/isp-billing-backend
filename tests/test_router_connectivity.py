"""Test MikroTik router connectivity (FTP, API, SSH)."""

import asyncio
import socket
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.models.router import Router, RouterStatus
from app.core.config import settings


def test_port(ip: str, port: int, timeout: int = 5) -> tuple[bool, str]:
    """Test if a port is open and accepting connections."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()

        if result == 0:
            return True, f"[OK] Port {port} is OPEN"
        else:
            return False, f"[FAIL] Port {port} is CLOSED (error code: {result})"
    except socket.timeout:
        return False, f"[FAIL] Port {port} TIMEOUT"
    except socket.gaierror:
        return False, f"[FAIL] Invalid IP address or DNS name"
    except Exception as e:
        return False, f"[FAIL] Port {port} ERROR: {e}"


async def test_router_connectivity():
    """Test connectivity to MikroTik router ports."""
    print("=" * 80)
    print("MikroTik Router Connectivity Test")
    print("=" * 80)

    # Get database connection
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as session:
            # Get most recent provisioned router
            print("\n[1] Fetching most recent provisioned router...")
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
            print(f"  IP Address: {router.ip_address}")
            print(f"  Username: {router.username}")
            print(f"  Status: {router.status}")

            # Test common MikroTik ports
            print(f"\n[2] Testing connectivity to {router.ip_address}...")
            print("-" * 80)

            ports_to_test = [
                (21, "FTP", "File transfer for template upload"),
                (22, "SSH", "Secure shell"),
                (2222, "SSH (Custom)", "Custom SSH port from bootstrap"),
                (23, "Telnet", "Telnet access"),
                (80, "HTTP", "Web interface"),
                (443, "HTTPS", "Secure web interface"),
                (8291, "Winbox", "Winbox management"),
                (router.port, "API", "MikroTik API"),
            ]

            results = {}
            for port, service, description in ports_to_test:
                print(f"\nTesting {service} (port {port}): {description}")
                is_open, message = test_port(router.ip_address, port)
                results[service] = is_open
                print(f"  {message}")

            # Summary
            print("\n" + "=" * 80)
            print("CONNECTIVITY SUMMARY")
            print("=" * 80)

            open_ports = sum(1 for is_open in results.values() if is_open)
            total_ports = len(results)

            print(f"\nOpen ports: {open_ports}/{total_ports}")
            print("\nServices Status:")
            for service, is_open in results.items():
                status = "[OK] REACHABLE" if is_open else "[FAIL] UNREACHABLE"
                print(f"  {service:20} {status}")

            # Specific FTP diagnosis
            print("\n" + "=" * 80)
            print("FTP DIAGNOSIS")
            print("=" * 80)

            if results.get("FTP"):
                print("[OK] FTP port (21) is reachable from this machine")
                print("  FTP service appears to be running and accessible")
            else:
                print("[FAIL] FTP port (21) is NOT reachable from this machine")
                print("\nPossible causes:")
                print("  1. FTP service is not actually running on the router")
                print("  2. Firewall is blocking FTP traffic")
                print("  3. FTP is bound to a different interface/IP")
                print("  4. Network routing issue between backend and router")
                print("\nTroubleshooting steps:")
                print("  1. Check FTP service on router:")
                print("     /ip service print")
                print("  2. Check firewall rules on router:")
                print("     /ip firewall filter print")
                print("  3. Check if Windows firewall is blocking outbound FTP:")
                print("     Windows Defender Firewall > Advanced Settings > Outbound Rules")
                print("  4. Verify network connectivity:")
                print(f"     ping {router.ip_address}")

            # Test from command line suggestion
            print("\n" + "=" * 80)
            print("MANUAL TESTING")
            print("=" * 80)
            print(f"\nTest FTP from command line:")
            print(f"  ftp {router.ip_address}")
            print(f"\nTest with telnet:")
            print(f"  telnet {router.ip_address} 21")
            print(f"\nTest with PowerShell:")
            print(f"  Test-NetConnection -ComputerName {router.ip_address} -Port 21")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_router_connectivity())
