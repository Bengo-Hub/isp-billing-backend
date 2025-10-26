"""Command generation and helpers for Codevertex MikroTik provisioning.

These helpers are imported by ProvisioningService to keep the service file
small and focused on orchestration. Functions here are stateless and accept
explicit parameters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provisioning import ProvisioningCommand, ProvisioningStatus, ServiceType


def load_command_templates() -> Dict[str, Dict[str, Any]]:
    return {
        "connection": {
            "system_info": "/system/resource/print",
            "identity_check": "/system/identity/print",
            "interface_list": "/interface/print",
            "ip_address_list": "/ip/address/print",
            "version_check": "/system/package/print where name=system",
        },
        "security": {
            "disable_default_services": [
                "/ip/service/set telnet disabled=yes",
                "/ip/service/set ftp disabled=yes",
                "/ip/service/set www disabled=yes",
                "/ip/service/set ssh port=2222",
            ],
            "create_firewall_rules": [
                "/ip/firewall/filter/add chain=input action=accept connection-state=established,related",
                "/ip/firewall/filter/add chain=input action=accept protocol=icmp",
                "/ip/firewall/filter/add chain=input action=accept dst-port=8728 protocol=tcp src-address={management_ip}",
                "/ip/firewall/filter/add chain=input action=drop",
            ],
        },
    }


def generate_configuration_commands(
    config: Dict[str, Any], service_type: ServiceType
) -> List[Dict[str, Any]]:
    commands: List[Dict[str, Any]] = []

    # Set system identity
    if "identity" in config:
        commands.append(
            {
                "type": "api_call",
                "command": f"/system/identity/set name={config['identity']}",
                "description": "Set system identity",
                "critical": False,
            }
        )

    # Bridge + ports
    if service_type in [ServiceType.HOTSPOT, ServiceType.BOTH]:
        bridge_name = config.get("bridge_name", "bridge-hotspot")
        commands.append(
            {
                "type": "api_call",
                "command": f"/interface/bridge/add name={bridge_name}",
                "description": f"Create bridge {bridge_name}",
                "critical": True,
            }
        )

        ports = (
            config.get("bridge_ports")
            if isinstance(config.get("bridge_ports"), list)
            else [config.get("interface", "ether2")]
        )
        for port in ports:
            commands.append(
                {
                    "type": "api_call",
                    "command": f"/interface/bridge/port/add interface={port} bridge={bridge_name}",
                    "description": f"Add {port} to bridge",
                    "critical": True,
                }
            )

    # IP pool
    if "ip_pool_start" in config and "ip_pool_end" in config:
        pool_name = config.get("pool_name", "ip-pool")
        ip_range = f"{config['ip_pool_start']}-{config['ip_pool_end']}"
        commands.append(
            {
                "type": "api_call",
                "command": f"/ip/pool/add name={pool_name} ranges={ip_range}",
                "description": f"Create IP pool {pool_name}",
                "critical": True,
            }
        )

    # DNS
    if "dns_servers" in config:
        dns_list = ",".join(config["dns_servers"])
        commands.append(
            {
                "type": "api_call",
                "command": f"/ip/dns/set servers={dns_list}",
                "description": "Configure DNS servers",
                "critical": False,
            }
        )

    return commands


def generate_hotspot_commands(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    commands: List[Dict[str, Any]] = []
    hotspot_name = config.get("hotspot_name", "ISP-Hotspot")
    interface = config.get("interface", "ether2")
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/hotspot/add name={hotspot_name} interface={interface}",
            "description": f"Create hotspot {hotspot_name}",
            "critical": True,
        }
    )
    if config.get("enable_anti_sharing", False):
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/hotspot/profile/set default login-by=http-chap session-timeout=1d idle-timeout=5m",
                "description": "Enable anti-sharing protection",
                "critical": False,
            }
        )
    if "walled_garden_hosts" in config:
        for host in config["walled_garden_hosts"]:
            commands.append(
                {
                    "type": "api_call",
                    "command": f"/ip/hotspot/walled-garden/add dst-host={host}",
                    "description": f"Add walled garden host {host}",
                    "critical": False,
                }
            )
    return commands


def generate_pppoe_commands(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    commands: List[Dict[str, Any]] = []
    service_name = config.get("service_name", "ISP-PPPoE")
    interface = config.get("interface", "ether2")
    profile_name = config.get("profile_name", "default-ppp")
    local_address = config.get("gateway", "172.31.1.1")
    ip_pool = config.get("pool_name", "ip-pool")
    commands.append(
        {
            "type": "api_call",
            "command": f"/ppp/profile/add name={profile_name} local-address={local_address} remote-address={ip_pool}",
            "description": f"Create PPP profile {profile_name}",
            "critical": True,
        }
    )
    commands.append(
        {
            "type": "api_call",
            "command": f"/interface/pppoe-server/server/add service-name={service_name} interface={interface} default-profile={profile_name}",
            "description": f"Enable PPPoE server {service_name}",
            "critical": True,
        }
    )
    return commands


async def execute_command_with_retry(
    db: AsyncSession,
    retry_delays: List[int],
    logger,
    session,
    api,
    command_data: Dict[str, Any],
) -> bool:
    command = ProvisioningCommand(
        session_id=session.id,
        command_type=command_data["type"],
        command=command_data["command"],
        description=command_data.get("description", ""),
        execution_order=command_data.get("order", 0),
        is_critical=command_data.get("critical", True),
        rollback_command=command_data.get("rollback", None),
    )
    db.add(command)
    await db.commit()

    max_retries = command.max_retries
    for attempt in range(max_retries + 1):
        try:
            command.executed_at = datetime.utcnow()
            command.status = ProvisioningStatus.IN_PROGRESS
            start_time = datetime.utcnow()
            if command_data["type"] == "api_call":
                result = await api.execute_command(command_data["command"])
            else:
                result = await api.execute_script(command_data["command"])
            command.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            command.output = str(result) if result else None
            command.success = True
            command.status = ProvisioningStatus.COMPLETED
            await db.commit()
            return True
        except Exception as e:  # noqa: BLE001
            command.retry_count = attempt + 1
            command.error_message = str(e)
            command.success = False
            if attempt < max_retries:
                # wait with backoff
                from asyncio import sleep

                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                await sleep(delay)
                command.status = ProvisioningStatus.PENDING
            else:
                command.status = ProvisioningStatus.FAILED
            await db.commit()
    return False


async def backup_router_configuration(db: AsyncSession, session, api, logger) -> None:
    try:
        config_data = await api.export_configuration()
        if config_data:
            from app.models.provisioning import RouterConfiguration
            import hashlib, json

            configuration = RouterConfiguration(
                router_id=session.router_id,
                session_id=session.id,
                configuration_type="backup",
                configuration_name=f"pre-provisioning-{datetime.utcnow().isoformat()}",
                configuration_data=config_data,
                is_backup=True,
                rollback_available=True,
                checksum=hashlib.sha256(json.dumps(config_data, sort_keys=True).encode()).hexdigest(),
            )
            db.add(configuration)
            await db.commit()
            logger.info(f"Created configuration backup for router {session.router_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to create configuration backup: {e}")


async def apply_security_configuration(api, config: Dict[str, Any], templates: Dict[str, Any], logger) -> None:
    try:
        for command in templates["security"]["disable_default_services"]:
            await api.execute_command(command)
        management_ip = config.get("management_ip", "0.0.0.0/0")
        for rule_template in templates["security"]["create_firewall_rules"]:
            rule = rule_template.format(management_ip=management_ip)
            await api.execute_command(rule)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Security configuration partially failed: {e}")


