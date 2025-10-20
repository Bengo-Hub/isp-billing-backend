"""Seed script for routers and router-related data."""

import asyncio
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

# Setup environment and path
sys.path.insert(0, str(Path(__file__).parent.parent))
import seed_env

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.router import Router, RouterDevice, RouterLog, RouterStatus, RouterType
from app.models.user import User, UserRole

logger = get_logger(__name__)


class RouterSeeder:
    """Router data seeder."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def seed_routers(self, count: int = 10, clear_existing: bool = False) -> List[Router]:
        """Seed routers with realistic MikroTik data."""
        if clear_existing:
            await self._clear_routers()

        routers = []
        
        # Create standard routers
        standard_routers = await self._create_standard_routers()
        routers.extend(standard_routers)
        
        # Create additional routers if needed
        if count > len(standard_routers):
            additional_routers = await self._create_additional_routers(count - len(standard_routers))
            routers.extend(additional_routers)
        
        # Create router devices for each router
        for router in routers:
            devices = await self._create_router_devices(router)
            
        await self.db.commit()
        
        self.logger.info(f"Seeded {len(routers)} routers")
        return routers

    async def _create_standard_routers(self) -> List[Router]:
        """Create standard MikroTik routers."""
        routers = []
        
        router_data = [
            {
                "name": "Main Office Router",
                "description": "Primary router for main office network",
                "ip_address": "192.168.1.1",
                "username": "admin",
                "password": "admin123",
                "location": "Main Office, Nairobi",
                "latitude": "-1.2921",
                "longitude": "36.8219",
                "status": RouterStatus.ONLINE,
                "uptime": 2592000  # 30 days
            },
            {
                "name": "Branch Office Router",
                "description": "Router for branch office connectivity",
                "ip_address": "192.168.2.1", 
                "username": "admin",
                "password": "admin123",
                "location": "Branch Office, Mombasa",
                "latitude": "-4.0435",
                "longitude": "39.6682",
                "status": RouterStatus.ONLINE,
                "uptime": 1728000  # 20 days
            },
            {
                "name": "Hotspot Router - Cafe",
                "description": "Dedicated hotspot router for cafe",
                "ip_address": "192.168.10.1",
                "username": "admin", 
                "password": "admin123",
                "location": "City Cafe, Nairobi CBD",
                "latitude": "-1.2864",
                "longitude": "36.8172",
                "status": RouterStatus.ONLINE,
                "uptime": 864000  # 10 days
            },
            {
                "name": "Residential Area Router",
                "description": "Router serving residential customers",
                "ip_address": "192.168.20.1",
                "username": "admin",
                "password": "admin123", 
                "location": "Westlands, Nairobi",
                "latitude": "-1.2676",
                "longitude": "36.8108",
                "status": RouterStatus.ONLINE,
                "uptime": 432000  # 5 days
            },
            {
                "name": "Backup Router",
                "description": "Backup router for redundancy",
                "ip_address": "192.168.100.1",
                "username": "admin",
                "password": "admin123",
                "location": "Data Center, Nairobi",
                "latitude": "-1.3032",
                "longitude": "36.8856",
                "status": RouterStatus.OFFLINE,
                "uptime": 0
            }
        ]
        
        for router_info in router_data:
            router = Router(
                name=router_info["name"],
                description=router_info["description"],
                router_type=RouterType.MIKROTIK,
                ip_address=router_info["ip_address"],
                port=8728,
                username=router_info["username"],
                password=router_info["password"],  # In production, this would be encrypted
                status=router_info["status"],
                is_active=True,
                last_seen=datetime.utcnow() - timedelta(minutes=random.randint(1, 60)) if router_info["status"] == RouterStatus.ONLINE else None,
                uptime=router_info["uptime"],
                location=router_info["location"],
                latitude=router_info["latitude"],
                longitude=router_info["longitude"],
                config=self._get_default_router_config(router_info["name"]),
                notes=f"Seeded router for {router_info['location']}",
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 180))
            )
            
            self.db.add(router)
            routers.append(router)
        
        return routers

    async def _create_additional_routers(self, count: int) -> List[Router]:
        """Create additional randomized routers."""
        routers = []
        
        locations = [
            "Kisumu", "Nakuru", "Eldoret", "Meru", "Nyeri", "Thika", "Machakos",
            "Garissa", "Malindi", "Lamu", "Kitale", "Kakamega", "Bungoma"
        ]
        
        router_types = ["Office", "Hotspot", "Residential", "Commercial", "Public"]
        
        for i in range(count):
            location = random.choice(locations)
            router_type_name = random.choice(router_types)
            
            # Generate IP in different subnets
            subnet = random.randint(30, 99)
            ip_address = f"192.168.{subnet}.1"
            
            router = Router(
                name=f"{router_type_name} Router {location}",
                description=f"{router_type_name} router deployed in {location}",
                router_type=RouterType.MIKROTIK,
                ip_address=ip_address,
                port=8728,
                username="admin",
                password="admin123",
                status=random.choice([RouterStatus.ONLINE, RouterStatus.OFFLINE, RouterStatus.MAINTENANCE]),
                is_active=random.choice([True, True, False]),  # 66% active
                last_seen=datetime.utcnow() - timedelta(minutes=random.randint(1, 1440)) if random.choice([True, False]) else None,
                uptime=random.randint(0, 2592000),  # 0 to 30 days
                location=f"{location}, Kenya",
                latitude=str(random.uniform(-4.5, 1.5)),  # Kenya latitude range
                longitude=str(random.uniform(33.5, 42.0)),  # Kenya longitude range
                config=self._get_default_router_config(f"{router_type_name} Router {location}"),
                notes=f"Auto-generated router for testing - {location}",
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 365))
            )
            
            self.db.add(router)
            routers.append(router)
        
        return routers

    async def _create_router_devices(self, router: Router) -> List[RouterDevice]:
        """Create connected devices for a router."""
        devices = []
        
        # Number of devices based on router status
        if router.status == RouterStatus.ONLINE:
            device_count = random.randint(5, 25)
        elif router.status == RouterStatus.OFFLINE:
            device_count = 0
        else:
            device_count = random.randint(0, 10)
        
        device_types = ["laptop", "smartphone", "tablet", "desktop", "smart_tv", "iot_device"]
        
        for i in range(device_count):
            device_type = random.choice(device_types)
            
            # Generate MAC address
            mac_parts = [f"{random.randint(0, 255):02x}" for _ in range(6)]
            mac_address = ":".join(mac_parts)
            
            # Generate IP in router subnet
            router_subnet = ".".join(router.ip_address.split(".")[:-1])
            device_ip = f"{router_subnet}.{random.randint(10, 254)}"
            
            device = RouterDevice(
                router_id=router.id,
                device_name=f"{device_type}_{i+1}",
                device_type=device_type,
                mac_address=mac_address,
                ip_address=device_ip,
                is_online=router.status == RouterStatus.ONLINE and random.choice([True, False]),
                last_seen=datetime.utcnow() - timedelta(minutes=random.randint(1, 60)) if router.status == RouterStatus.ONLINE else None,
                bytes_sent=random.randint(1000000, 100000000),  # 1MB to 100MB
                bytes_received=random.randint(10000000, 1000000000),  # 10MB to 1GB
                uptime=random.randint(0, router.uptime) if router.uptime > 0 else 0,
                created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 720))
            )
            
            self.db.add(device)
            devices.append(device)
        
        # Create some router logs
        await self._create_router_logs(router)
        
        return devices

    async def _create_router_logs(self, router: Router) -> List[RouterLog]:
        """Create router operation logs."""
        logs = []
        
        log_actions = [
            "connect", "disconnect", "create_user", "delete_user", "update_config",
            "backup_config", "sync_status", "reboot", "firmware_update", "monitor_check"
        ]
        
        log_count = random.randint(10, 50)
        
        for i in range(log_count):
            action = random.choice(log_actions)
            success = random.choice([True, True, True, False])  # 75% success rate
            
            log = RouterLog(
                router_id=router.id,
                action=action,
                details=f"Automated {action} operation",
                success=success,
                error_message=f"Simulated error for {action}" if not success else None,
                ip_address=router.ip_address,
                created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 720))
            )
            
            self.db.add(log)
            logs.append(log)
        
        return logs

    def _get_default_router_config(self, router_name: str) -> str:
        """Get default router configuration JSON."""
        config = {
            "identity": router_name,
            "interfaces": {
                "ether1": {"description": "WAN", "enabled": True},
                "ether2": {"description": "LAN", "enabled": True},
                "ether3": {"description": "WiFi", "enabled": True},
                "bridge1": {"description": "LAN Bridge", "enabled": True}
            },
            "ip_pools": {
                "hotspot_pool": {"range": "172.31.1.1-172.31.1.254"},
                "pppoe_pool": {"range": "172.31.2.1-172.31.2.254"}
            },
            "dns_servers": ["8.8.8.8", "8.8.4.4"],
            "ntp_servers": ["pool.ntp.org"],
            "services": {
                "hotspot": {"enabled": True, "interface": "ether2"},
                "pppoe": {"enabled": True, "interface": "ether2"},
                "api": {"enabled": True, "port": 8728},
                "ssh": {"enabled": True, "port": 22}
            },
            "firewall": {
                "enabled": True,
                "rules": [
                    {"chain": "input", "action": "accept", "connection_state": "established,related"},
                    {"chain": "input", "action": "accept", "protocol": "icmp"},
                    {"chain": "input", "action": "drop"}
                ]
            }
        }
        
        import json
        return json.dumps(config, indent=2)

    async def _clear_routers(self):
        """Clear existing routers."""
        from sqlalchemy import delete
        
        # Delete in correct order to respect foreign key constraints
        await self.db.execute(delete(RouterLog))
        await self.db.execute(delete(RouterDevice))
        await self.db.execute(delete(Router))
        
        await self.db.commit()
        self.logger.info("Cleared existing routers")


async def seed_routers(count: int = 10, clear_existing: bool = False) -> List[Router]:
    """Seed routers."""
    async with AsyncSessionLocal() as db:
        seeder = RouterSeeder(db)
        return await seeder.seed_routers(count, clear_existing)


if __name__ == "__main__":
    asyncio.run(seed_routers(count=10, clear_existing=True))
