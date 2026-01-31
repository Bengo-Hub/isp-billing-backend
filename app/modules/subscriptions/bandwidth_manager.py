"""
Bandwidth Profile Management Service.

This module handles synchronization of service plan bandwidth profiles
to MikroTik routers. It ensures that rate limits defined in the database
are properly configured as profiles/queues on the router.

Key Features:
- Sync bandwidth profiles from service plans to routers
- Create hotspot user profiles with rate limits
- Create PPP profiles with rate limits
- Manage simple queues for active users
- Handle burst configurations
- Support for shared bandwidth limits
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.router import Router
from app.models.plan import ServicePlan
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionType
from app.integrations.mikrotik import get_mikrotik_client

logger = get_logger(__name__)


class BandwidthProfileManager:
    """
    Manages bandwidth profiles on MikroTik routers.

    This service ensures that all service plans have corresponding
    bandwidth profiles configured on the routers where they're used.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def format_rate_limit(
        download_kbps: int,
        upload_kbps: int,
        burst_download_kbps: Optional[int] = None,
        burst_upload_kbps: Optional[int] = None,
        burst_threshold_percent: int = 75,
        burst_time_seconds: int = 10
    ) -> str:
        """
        Format bandwidth limits in MikroTik rate-limit format.

        MikroTik format: rx-rate[/tx-rate] [rx-burst-rate[/tx-burst-rate]
                         [rx-burst-threshold[/tx-burst-threshold]
                         [rx-burst-time[/tx-burst-time]]]]

        Note: In MikroTik, rx = download (from user's perspective = router's transmit)
              tx = upload (from user's perspective = router's receive)

        Args:
            download_kbps: Download speed in Kbps
            upload_kbps: Upload speed in Kbps
            burst_download_kbps: Burst download speed (optional)
            burst_upload_kbps: Burst upload speed (optional)
            burst_threshold_percent: Percentage of limit to trigger burst
            burst_time_seconds: Duration of burst allowance

        Returns:
            MikroTik-formatted rate limit string
        """
        # Convert to k notation
        download = f"{download_kbps}k"
        upload = f"{upload_kbps}k"

        if burst_download_kbps and burst_upload_kbps:
            burst_download = f"{burst_download_kbps}k"
            burst_upload = f"{burst_upload_kbps}k"

            # Calculate thresholds
            threshold_download = f"{int(download_kbps * burst_threshold_percent / 100)}k"
            threshold_upload = f"{int(upload_kbps * burst_threshold_percent / 100)}k"

            burst_time = f"{burst_time_seconds}s"

            # Full format with burst: rx/tx burst-rx/burst-tx threshold-rx/threshold-tx time/time
            return (
                f"{upload}/{download} "
                f"{burst_upload}/{burst_download} "
                f"{threshold_upload}/{threshold_download} "
                f"{burst_time}/{burst_time}"
            )

        # Simple format: upload/download (tx/rx from router perspective)
        return f"{upload}/{download}"

    @staticmethod
    def format_simple_queue_target(ip_address: str) -> str:
        """Format target for simple queue."""
        return ip_address if "/" in ip_address else f"{ip_address}/32"

    async def sync_all_profiles_to_router(
        self,
        router: Router,
        plans: Optional[List[ServicePlan]] = None
    ) -> Dict[str, Any]:
        """
        Sync all bandwidth profiles to a specific router.

        Args:
            router: Router to sync profiles to
            plans: Optional list of plans. If None, fetches all active plans.

        Returns:
            Dict with sync results
        """
        results = {
            "router_id": router.id,
            "success": False,
            "hotspot_profiles": {"created": 0, "updated": 0, "errors": []},
            "ppp_profiles": {"created": 0, "updated": 0, "errors": []},
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            # Get plans if not provided
            if plans is None:
                plan_query = select(ServicePlan).where(ServicePlan.is_active == True)
                plan_result = await self.db.execute(plan_query)
                plans = plan_result.scalars().all()

            if not plans:
                results["success"] = True
                results["message"] = "No plans to sync"
                return results

            # Connect to router
            client = get_mikrotik_client()
            try:
                connection = await client.connect(
                    ip_address=router.ip_address,
                    username=router.username,
                    password=router.password,
                    port=router.port
                )
            except Exception as conn_error:
                results["error"] = f"Failed to connect to router: {conn_error}"
                return results

            try:
                # Sync hotspot profiles
                for plan in plans:
                    # Create hotspot profile
                    hotspot_result = await self._sync_hotspot_profile(client, connection, plan)
                    if hotspot_result["success"]:
                        if hotspot_result.get("created"):
                            results["hotspot_profiles"]["created"] += 1
                        else:
                            results["hotspot_profiles"]["updated"] += 1
                    else:
                        results["hotspot_profiles"]["errors"].append({
                            "plan_id": plan.id,
                            "error": hotspot_result.get("error")
                        })

                    # Create PPP profile
                    ppp_result = await self._sync_ppp_profile(client, connection, plan)
                    if ppp_result["success"]:
                        if ppp_result.get("created"):
                            results["ppp_profiles"]["created"] += 1
                        else:
                            results["ppp_profiles"]["updated"] += 1
                    else:
                        results["ppp_profiles"]["errors"].append({
                            "plan_id": plan.id,
                            "error": ppp_result.get("error")
                        })

                results["success"] = True

            finally:
                await client.disconnect(router.ip_address, router.port)

            return results

        except Exception as e:
            logger.error(f"Failed to sync profiles to router {router.id}: {e}")
            results["error"] = str(e)
            return results

    async def _sync_hotspot_profile(
        self,
        client,
        connection,
        plan: ServicePlan
    ) -> Dict[str, Any]:
        """Sync a single hotspot user profile."""
        result = {"success": False}

        try:
            profile_name = f"plan_{plan.id}_{plan.name[:20].replace(' ', '_')}"

            # Format rate limit
            rate_limit = self.format_rate_limit(
                download_kbps=plan.download_speed,
                upload_kbps=plan.upload_speed,
                burst_download_kbps=getattr(plan, 'burst_download', None),
                burst_upload_kbps=getattr(plan, 'burst_upload', None)
            )

            # Get existing profiles
            profiles = await client.execute_command(
                connection, "/ip/hotspot/user/profile", method="get"
            )

            existing = next(
                (p for p in (profiles or []) if p.get('name') == profile_name),
                None
            )

            profile_data = {
                "name": profile_name,
                "rate-limit": rate_limit,
                "shared-users": str(getattr(plan, 'shared_users', 1)),
                "idle-timeout": "15m",
                "keepalive-timeout": "2m",
                "status-autorefresh": "1m"
            }

            # Add session timeout based on plan duration (if applicable)
            if hasattr(plan, 'session_timeout_minutes') and plan.session_timeout_minutes:
                profile_data["session-timeout"] = f"{plan.session_timeout_minutes}m"

            if existing:
                # Update existing profile
                await client.execute_command(
                    connection, "/ip/hotspot/user/profile", method="set",
                    id=existing['.id'],
                    **profile_data
                )
                result["success"] = True
                result["created"] = False
                logger.info(f"Updated hotspot profile: {profile_name}")
            else:
                # Create new profile
                await client.execute_command(
                    connection, "/ip/hotspot/user/profile", method="add",
                    **profile_data
                )
                result["success"] = True
                result["created"] = True
                logger.info(f"Created hotspot profile: {profile_name}")

            return result

        except Exception as e:
            logger.error(f"Failed to sync hotspot profile for plan {plan.id}: {e}")
            result["error"] = str(e)
            return result

    async def _sync_ppp_profile(
        self,
        client,
        connection,
        plan: ServicePlan
    ) -> Dict[str, Any]:
        """Sync a single PPP profile."""
        result = {"success": False}

        try:
            profile_name = f"plan_{plan.id}_{plan.name[:20].replace(' ', '_')}"

            # Format rate limit
            rate_limit = self.format_rate_limit(
                download_kbps=plan.download_speed,
                upload_kbps=plan.upload_speed,
                burst_download_kbps=getattr(plan, 'burst_download', None),
                burst_upload_kbps=getattr(plan, 'burst_upload', None)
            )

            # Get existing profiles
            profiles = await client.execute_command(
                connection, "/ppp/profile", method="get"
            )

            existing = next(
                (p for p in (profiles or []) if p.get('name') == profile_name),
                None
            )

            profile_data = {
                "name": profile_name,
                "rate-limit": rate_limit,
                "only-one": "yes" if getattr(plan, 'shared_users', 1) == 1 else "no",
                "session-timeout": "0s",  # No session timeout by default
                "idle-timeout": "15m"
            }

            # Add local/remote address if configured
            if hasattr(plan, 'local_address') and plan.local_address:
                profile_data["local-address"] = plan.local_address
            if hasattr(plan, 'remote_address') and plan.remote_address:
                profile_data["remote-address"] = plan.remote_address

            # Add DNS servers if configured
            if hasattr(plan, 'dns_servers') and plan.dns_servers:
                profile_data["dns-server"] = plan.dns_servers

            if existing:
                # Update existing profile
                await client.execute_command(
                    connection, "/ppp/profile", method="set",
                    id=existing['.id'],
                    **profile_data
                )
                result["success"] = True
                result["created"] = False
                logger.info(f"Updated PPP profile: {profile_name}")
            else:
                # Create new profile
                await client.execute_command(
                    connection, "/ppp/profile", method="add",
                    **profile_data
                )
                result["success"] = True
                result["created"] = True
                logger.info(f"Created PPP profile: {profile_name}")

            return result

        except Exception as e:
            logger.error(f"Failed to sync PPP profile for plan {plan.id}: {e}")
            result["error"] = str(e)
            return result

    async def create_user_queue(
        self,
        client,
        connection,
        username: str,
        ip_address: str,
        plan: ServicePlan,
        parent_queue: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a simple queue for a specific user.

        This provides per-user bandwidth control beyond profile limits.
        Useful for traffic shaping and monitoring individual usage.

        Args:
            client: MikroTik client
            connection: Active router connection
            username: Username for queue name
            ip_address: User's IP address (target)
            plan: Service plan for rate limits
            parent_queue: Optional parent queue for hierarchical QoS

        Returns:
            Dict with creation result
        """
        result = {"success": False}

        try:
            queue_name = f"user_{username}"

            # Format limits
            max_limit = f"{plan.upload_speed}k/{plan.download_speed}k"

            # Calculate burst if available
            burst_limit = None
            burst_threshold = None
            if hasattr(plan, 'burst_download') and plan.burst_download:
                burst_limit = f"{getattr(plan, 'burst_upload', plan.upload_speed)}k/{plan.burst_download}k"
                burst_threshold = f"{int(plan.upload_speed * 0.75)}k/{int(plan.download_speed * 0.75)}k"

            # Check for existing queue
            queues = await client.execute_command(
                connection, "/queue/simple", method="get"
            )

            existing = next(
                (q for q in (queues or []) if q.get('name') == queue_name),
                None
            )

            queue_data = {
                "name": queue_name,
                "target": self.format_simple_queue_target(ip_address),
                "max-limit": max_limit,
                "comment": f"Auto-created for user {username}"
            }

            if burst_limit:
                queue_data["burst-limit"] = burst_limit
                queue_data["burst-threshold"] = burst_threshold
                queue_data["burst-time"] = "10s/10s"

            if parent_queue:
                queue_data["parent"] = parent_queue

            if existing:
                # Update existing queue
                await client.execute_command(
                    connection, "/queue/simple", method="set",
                    id=existing['.id'],
                    **queue_data
                )
                result["success"] = True
                result["updated"] = True
            else:
                # Create new queue
                await client.execute_command(
                    connection, "/queue/simple", method="add",
                    **queue_data
                )
                result["success"] = True
                result["created"] = True

            return result

        except Exception as e:
            logger.error(f"Failed to create queue for user {username}: {e}")
            result["error"] = str(e)
            return result

    async def remove_user_queue(
        self,
        client,
        connection,
        username: str
    ) -> Dict[str, Any]:
        """Remove a user's simple queue."""
        result = {"success": False}

        try:
            queue_name = f"user_{username}"

            queues = await client.execute_command(
                connection, "/queue/simple", method="get"
            )

            existing = next(
                (q for q in (queues or []) if q.get('name') == queue_name),
                None
            )

            if existing:
                await client.execute_command(
                    connection, "/queue/simple", method="remove",
                    id=existing['.id']
                )
                result["success"] = True
                result["removed"] = True
            else:
                result["success"] = True
                result["message"] = "Queue not found"

            return result

        except Exception as e:
            logger.error(f"Failed to remove queue for user {username}: {e}")
            result["error"] = str(e)
            return result

    async def get_user_bandwidth_usage(
        self,
        client,
        connection,
        username: str
    ) -> Dict[str, Any]:
        """
        Get current bandwidth usage for a user from their queue.

        Returns:
            Dict with bytes-in, bytes-out, rate-in, rate-out
        """
        result = {"success": False}

        try:
            queue_name = f"user_{username}"

            queues = await client.execute_command(
                connection, "/queue/simple", method="get"
            )

            queue = next(
                (q for q in (queues or []) if q.get('name') == queue_name),
                None
            )

            if queue:
                result["success"] = True
                result["usage"] = {
                    "bytes_in": int(queue.get('bytes-in', 0)),
                    "bytes_out": int(queue.get('bytes-out', 0)),
                    "packets_in": int(queue.get('packets-in', 0)),
                    "packets_out": int(queue.get('packets-out', 0)),
                    "rate": queue.get('rate', '0/0'),
                    "queued_bytes": queue.get('queued-bytes', '0/0'),
                    "queued_packets": queue.get('queued-packets', '0/0')
                }
            else:
                result["message"] = "Queue not found"

            return result

        except Exception as e:
            logger.error(f"Failed to get bandwidth usage for {username}: {e}")
            result["error"] = str(e)
            return result

    async def create_parent_queue(
        self,
        client,
        connection,
        name: str,
        max_download_kbps: int,
        max_upload_kbps: int
    ) -> Dict[str, Any]:
        """
        Create a parent queue for hierarchical QoS.

        Parent queues can be used to limit total bandwidth for a group
        of users (e.g., per organization or per interface).

        Args:
            client: MikroTik client
            connection: Active router connection
            name: Queue name
            max_download_kbps: Maximum download for all children
            max_upload_kbps: Maximum upload for all children

        Returns:
            Dict with creation result
        """
        result = {"success": False}

        try:
            # Check for existing
            queues = await client.execute_command(
                connection, "/queue/simple", method="get"
            )

            existing = next(
                (q for q in (queues or []) if q.get('name') == name),
                None
            )

            queue_data = {
                "name": name,
                "target": "0.0.0.0/0",  # Will be overridden by child queues
                "max-limit": f"{max_upload_kbps}k/{max_download_kbps}k",
                "queue": "pcq-upload-default/pcq-download-default",
                "comment": "Parent queue for bandwidth aggregation"
            }

            if existing:
                await client.execute_command(
                    connection, "/queue/simple", method="set",
                    id=existing['.id'],
                    **queue_data
                )
                result["success"] = True
                result["updated"] = True
            else:
                await client.execute_command(
                    connection, "/queue/simple", method="add",
                    **queue_data
                )
                result["success"] = True
                result["created"] = True

            return result

        except Exception as e:
            logger.error(f"Failed to create parent queue {name}: {e}")
            result["error"] = str(e)
            return result

    async def sync_all_routers(self) -> Dict[str, Any]:
        """
        Sync bandwidth profiles to all online routers.

        This should be called after plan changes to ensure all
        routers have the updated bandwidth profiles.

        Returns:
            Dict with sync results for all routers
        """
        results = {
            "total_routers": 0,
            "successful": 0,
            "failed": 0,
            "router_results": [],
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            # Get all online routers
            router_query = select(Router).where(Router.status == "online")
            router_result = await self.db.execute(router_query)
            routers = router_result.scalars().all()

            results["total_routers"] = len(routers)

            # Get all active plans once
            plan_query = select(ServicePlan).where(ServicePlan.is_active == True)
            plan_result = await self.db.execute(plan_query)
            plans = plan_result.scalars().all()

            for router in routers:
                sync_result = await self.sync_all_profiles_to_router(router, plans)
                results["router_results"].append({
                    "router_id": router.id,
                    "router_name": router.name,
                    "result": sync_result
                })

                if sync_result["success"]:
                    results["successful"] += 1
                else:
                    results["failed"] += 1

            return results

        except Exception as e:
            logger.error(f"Failed to sync all routers: {e}")
            results["error"] = str(e)
            return results
