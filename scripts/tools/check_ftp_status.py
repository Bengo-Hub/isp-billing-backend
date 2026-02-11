"""Check FTP service status on MikroTik router."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.routers.mikrotik import get_mikrotik_client

async def main():
    client = get_mikrotik_client()

    router_ip = "192.168.100.7"
    username = "codevertex_api_user"
    password = "Vertex2020"

    print(f"Checking FTP service status on {router_ip}...")

    try:
        # Connect to router
        connection = await client.connect(router_ip, username, password, 8728)

        # Check FTP service status
        print("\n=== FTP Service Status ===")
        services = await client.execute_command(connection, "/ip/service/print")

        for service in services:
            if service.get('name') == 'ftp':
                print(f"Name: {service.get('name')}")
                print(f"Port: {service.get('port')}")
                print(f"Disabled: {service.get('disabled')}")
                print(f"Address: {service.get('address', 'any')}")
                break
        else:
            print("FTP service not found in service list")

        await client.disconnect(router_ip, 8728)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
