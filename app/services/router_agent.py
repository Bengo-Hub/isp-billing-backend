"""Router agent service for polling-based command queue architecture.

Handles command queuing, poll processing, and result reporting
for MikroTik routers running the CodeVertex polling agent.
"""

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import get_password_hash, verify_password
from app.models.router import Router
from app.models.router_command import CommandStatus, RouterCommand

logger = get_logger(__name__)


class RouterAgentService:
    """Manages command queue and poll handling for router polling agents."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- Command Queue ----

    async def queue_command(
        self,
        router_id: int,
        action: str,
        params: Dict[str, Any],
        priority: int = 5,
        source: Optional[str] = None,
        source_id: Optional[str] = None,
        expires_in_seconds: int = None,
    ) -> RouterCommand:
        """Queue a command for a router to pick up on its next poll.

        Args:
            router_id: Target router ID
            action: Command action (create_user, disable_user, enable_user, disconnect, set_queue, run_script)
            params: Action-specific parameters
            priority: 1=critical, 5=normal, 9=low
            source: What triggered this command (subscription_sync, manual, billing_cycle)
            source_id: Related entity ID (e.g., subscription_id)
            expires_in_seconds: Command expiry in seconds (default from config)
        """
        if expires_in_seconds is None:
            expires_in_seconds = settings.agent_command_expiry_hours * 3600

        command = RouterCommand(
            router_id=router_id,
            action=action,
            params=params,
            priority=priority,
            source=source,
            source_id=source_id,
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in_seconds),
        )
        self.db.add(command)
        await self.db.flush()

        logger.info(
            f"Queued command {command.id}: {action} for router {router_id} "
            f"(priority={priority}, source={source})"
        )
        return command

    async def get_pending_commands(
        self, router_id: int, limit: int = None
    ) -> List[RouterCommand]:
        """Get pending commands for a router, ordered by priority then creation time."""
        if limit is None:
            limit = settings.agent_max_commands_per_poll

        result = await self.db.execute(
            select(RouterCommand)
            .where(
                and_(
                    RouterCommand.router_id == router_id,
                    RouterCommand.status == CommandStatus.PENDING,
                    # Exclude expired commands
                    (RouterCommand.expires_at.is_(None))
                    | (RouterCommand.expires_at > datetime.utcnow()),
                )
            )
            .order_by(RouterCommand.priority.asc(), RouterCommand.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_commands_sent(self, command_ids: List[str]) -> None:
        """Mark commands as sent (included in a poll response)."""
        if not command_ids:
            return
        await self.db.execute(
            update(RouterCommand)
            .where(RouterCommand.id.in_(command_ids))
            .values(status=CommandStatus.SENT, sent_at=datetime.utcnow())
        )

    # ---- Poll Handling ----

    async def handle_poll(
        self, router_id: int, telemetry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process a poll from a router agent.

        Updates router status/telemetry, returns pending commands.

        Returns:
            {"commands": [...], "poll_interval": int, "agent_version": str}
        """
        router = await self.db.get(Router, router_id)
        if not router:
            logger.warning(f"Poll from unknown router_id={router_id}")
            return {"commands": [], "poll_interval": settings.agent_default_poll_interval}

        now = datetime.utcnow()

        # Update router telemetry
        router.last_seen = now
        router.last_poll_at = now
        router.status = "online"

        if telemetry.get("cpu_load") is not None:
            router.cpu_load = telemetry["cpu_load"]
        if telemetry.get("free_memory") is not None:
            router.free_memory = telemetry["free_memory"]
        if telemetry.get("total_memory") is not None:
            router.total_memory = telemetry["total_memory"]
        if telemetry.get("free_hdd_space") is not None:
            router.free_hdd_space = telemetry["free_hdd_space"]
        if telemetry.get("total_hdd_space") is not None:
            router.total_hdd_space = telemetry["total_hdd_space"]
        if telemetry.get("uptime") is not None:
            router.uptime = self._parse_uptime(telemetry["uptime"])
        if telemetry.get("version"):
            router.routeros_version = telemetry["version"]

        # Store telemetry in Redis for fast dashboard access
        try:
            redis = await get_redis()
            redis_key = f"router:status:{router_id}"
            await redis.hset(redis_key, "cpu_load", str(telemetry.get("cpu_load", 0)))
            await redis.hset(redis_key, "free_memory", str(telemetry.get("free_memory", 0)))
            await redis.hset(redis_key, "total_memory", str(telemetry.get("total_memory", 0)))
            await redis.hset(redis_key, "active_pppoe", str(telemetry.get("active_pppoe", 0)))
            await redis.hset(redis_key, "active_hotspot", str(telemetry.get("active_hotspot", 0)))
            await redis.hset(redis_key, "last_poll", now.isoformat())
            await redis.hset(redis_key, "status", "online")
            await redis.expire(redis_key, 300)  # 5-minute TTL
        except Exception as e:
            logger.warning(f"Failed to update Redis telemetry for router {router_id}: {e}")

        # Get pending commands
        commands = await self.get_pending_commands(router_id)

        # Mark them as sent
        command_ids = [cmd.id for cmd in commands]
        if command_ids:
            await self.mark_commands_sent(command_ids)

        await self.db.commit()

        # Format commands for response
        formatted_commands = [
            {
                "id": cmd.id,
                "action": cmd.action,
                "params": cmd.params,
            }
            for cmd in commands
        ]

        logger.debug(
            f"Poll from router {router_id}: "
            f"{len(formatted_commands)} commands dispatched"
        )

        return {
            "commands": formatted_commands,
            "poll_interval": router.agent_poll_interval,
            "agent_version": settings.agent_script_version,
        }

    # ---- Result Reporting ----

    async def handle_report(
        self, router_id: int, results: List[Dict[str, Any]]
    ) -> None:
        """Process command execution results from a router agent.

        Args:
            router_id: Reporting router
            results: List of {"id": str, "status": "success"|"failed", "message": str}
        """
        for result in results:
            command_id = result.get("id")
            status = result.get("status", "failed")
            message = result.get("message", "")

            await self.process_command_result(command_id, status, message)

        await self.db.commit()

    async def process_command_result(
        self, command_id: str, status: str, message: str
    ) -> None:
        """Process a single command result."""
        command = await self.db.get(RouterCommand, command_id)
        if not command:
            logger.warning(f"Result for unknown command_id={command_id}")
            return

        now = datetime.utcnow()

        if status == "success":
            command.status = CommandStatus.SUCCESS
            command.completed_at = now
            command.result_message = message or "OK"

            # If this was a subscription sync command, update subscription
            if command.source == "subscription_sync" and command.source_id:
                await self._update_subscription_sync_status(
                    command.source_id, synced=True
                )

            logger.info(
                f"Command {command_id} ({command.action}) succeeded "
                f"on router {command.router_id}"
            )

        elif status == "failed":
            command.retry_count += 1
            command.result_message = message

            if command.retry_count >= command.max_retries:
                command.status = CommandStatus.FAILED
                command.completed_at = now
                logger.error(
                    f"Command {command_id} ({command.action}) failed permanently "
                    f"on router {command.router_id}: {message}"
                )
            else:
                # Reset to pending for retry on next poll
                command.status = CommandStatus.PENDING
                command.sent_at = None
                logger.warning(
                    f"Command {command_id} ({command.action}) failed, "
                    f"retry {command.retry_count}/{command.max_retries}: {message}"
                )

    async def _update_subscription_sync_status(
        self, subscription_id: str, synced: bool
    ) -> None:
        """Update subscription router sync status after command completes."""
        from app.models.subscription import Subscription

        try:
            sub_id = int(subscription_id)
        except (ValueError, TypeError):
            return

        subscription = await self.db.get(Subscription, sub_id)
        if subscription:
            subscription.is_router_synced = synced
            subscription.last_router_sync = datetime.utcnow()
            logger.info(
                f"Subscription {sub_id} router sync updated: synced={synced}"
            )

    # ---- Token Management ----

    async def generate_agent_token(self, router_id: int) -> str:
        """Generate and store a per-router agent authentication token.

        Returns the plain token (to embed in bootstrap script).
        The hashed version is stored in the database.
        """
        router = await self.db.get(Router, router_id)
        if not router:
            raise ValueError(f"Router {router_id} not found")

        # Generate a cryptographically secure token
        plain_token = secrets.token_hex(32)  # 64-char hex string

        # Store hashed version for verification
        router.agent_token = get_password_hash(plain_token)
        # Store plain version (encrypted at rest by the column) for bootstrap script regeneration
        router.agent_token_plain = plain_token

        await self.db.flush()

        logger.info(f"Generated agent token for router {router_id}")
        return plain_token

    async def verify_agent_token(self, router_id: int, token: str) -> bool:
        """Verify a router agent token against the stored hash."""
        router = await self.db.get(Router, router_id)
        if not router or not router.agent_token:
            return False

        return verify_password(token, router.agent_token)

    # ---- Cleanup ----

    async def cleanup_expired_commands(self) -> int:
        """Mark expired pending/sent commands as expired. Returns count."""
        now = datetime.utcnow()
        result = await self.db.execute(
            update(RouterCommand)
            .where(
                and_(
                    RouterCommand.status.in_([CommandStatus.PENDING, CommandStatus.SENT]),
                    RouterCommand.expires_at.isnot(None),
                    RouterCommand.expires_at < now,
                )
            )
            .values(status=CommandStatus.EXPIRED, completed_at=now)
        )
        count = result.rowcount
        await self.db.commit()

        if count > 0:
            logger.info(f"Cleaned up {count} expired router commands")
        return count

    async def reset_stale_sent_commands(self, stale_threshold_minutes: int = 5) -> int:
        """Reset commands stuck in 'sent' status back to pending for retry.

        Commands may get stuck in 'sent' if a router picks them up but
        never reports back (e.g., router rebooted).
        """
        threshold = datetime.utcnow() - timedelta(minutes=stale_threshold_minutes)
        result = await self.db.execute(
            update(RouterCommand)
            .where(
                and_(
                    RouterCommand.status == CommandStatus.SENT,
                    RouterCommand.sent_at < threshold,
                    RouterCommand.retry_count < RouterCommand.max_retries,
                )
            )
            .values(status=CommandStatus.PENDING, sent_at=None)
        )
        count = result.rowcount
        await self.db.commit()

        if count > 0:
            logger.info(f"Reset {count} stale sent commands back to pending")
        return count

    # ---- Pipe-Delimited Formatting (for RouterOS v6 compatibility) ----

    def format_commands_pipe_delimited(
        self, commands: List[Dict[str, Any]]
    ) -> str:
        """Format commands as pipe-delimited text for RouterOS v6 parsing.

        Format: action|param1|param2|...|command_id
        One command per line.

        Examples:
            disconnect|user123|cmd-uuid-1
            disable_user|john|hotspot|cmd-uuid-2
            create_user|jane|pass123|pppoe|default|10M/5M|cmd-uuid-3
            enable_user|john|pppoe|cmd-uuid-4
            set_queue|user123|20M/10M|cmd-uuid-5
        """
        lines = []
        for cmd in commands:
            action = cmd["action"]
            params = cmd["params"]
            cmd_id = cmd["id"]

            if action == "disconnect":
                lines.append(f"disconnect|{params.get('username', '')}|{cmd_id}")

            elif action == "disable_user":
                lines.append(
                    f"disable_user|{params.get('username', '')}|"
                    f"{params.get('type', 'pppoe')}|{cmd_id}"
                )

            elif action == "enable_user":
                lines.append(
                    f"enable_user|{params.get('username', '')}|"
                    f"{params.get('type', 'pppoe')}|{cmd_id}"
                )

            elif action == "create_user":
                lines.append(
                    f"create_user|{params.get('username', '')}|"
                    f"{params.get('password', '')}|"
                    f"{params.get('type', 'pppoe')}|"
                    f"{params.get('profile', 'default')}|"
                    f"{params.get('rate_limit', '')}|{cmd_id}"
                )

            elif action == "set_queue":
                lines.append(
                    f"set_queue|{params.get('target', '')}|"
                    f"{params.get('max_limit', '')}|{cmd_id}"
                )

            elif action == "fetch_import":
                # url must not contain a pipe (JWT/base64url + query string is safe)
                lines.append(f"fetch_import|{params.get('url', '')}|{cmd_id}")

            elif action == "run_script":
                # For run_script, base64 encode the script content
                import base64
                script = params.get("script", "")
                encoded = base64.b64encode(script.encode()).decode()
                lines.append(f"run_script|{encoded}|{cmd_id}")

            else:
                # Generic: serialize params as key=value pairs
                param_str = ",".join(f"{k}={v}" for k, v in params.items())
                lines.append(f"{action}|{param_str}|{cmd_id}")

        return "\n".join(lines)

    # ---- Helpers ----

    @staticmethod
    def _parse_uptime(uptime_str: str) -> int:
        """Parse a RouterOS uptime string to seconds.

        Handles BOTH formats RouterOS emits:
        - letter format: "3d12h45m30s", "12h30m", "45m10s", "30s", "1w2d3h"
        - colon format:  "00:10:04", "5:18:57", "1d 02:03:04"
        """
        if isinstance(uptime_str, (int, float)):
            return int(uptime_str)

        s = str(uptime_str).strip()
        if not s:
            return 0

        # Colon format (optionally prefixed with "<days>d "), e.g. "1d 02:03:04"
        if ":" in s:
            total = 0
            day_part = ""
            time_part = s
            if "d" in s:
                # split "1d 02:03:04" or "1d02:03:04"
                idx = s.find("d")
                day_part = s[:idx].strip()
                time_part = s[idx + 1:].strip()
                try:
                    total += int(day_part) * 86400
                except ValueError:
                    pass
            bits = time_part.split(":")
            try:
                nums = [int(b) for b in bits]
                if len(nums) == 3:
                    total += nums[0] * 3600 + nums[1] * 60 + nums[2]
                elif len(nums) == 2:
                    total += nums[0] * 60 + nums[1]
                elif len(nums) == 1:
                    total += nums[0]
            except ValueError:
                pass
            return total

        # Letter format
        total = 0
        current = ""
        for char in str(uptime_str):
            if char.isdigit():
                current += char
            elif char == "w" and current:
                total += int(current) * 604800
                current = ""
            elif char == "d" and current:
                total += int(current) * 86400
                current = ""
            elif char == "h" and current:
                total += int(current) * 3600
                current = ""
            elif char == "m" and current:
                total += int(current) * 60
                current = ""
            elif char == "s" and current:
                total += int(current)
                current = ""
        return total
