"""
Subscription-to-Router Synchronization Service.

This module handles the critical function of syncing subscriptions from the
billing database to MikroTik routers. When a subscription is created, renewed,
suspended, or expired, the corresponding user must be managed on the router.

Key Features:
- Create/delete users on router when subscription changes
- Sync bandwidth profiles based on service plan
- Track sync status in database
- Handle failures with retry logic
- Disconnect active sessions when subscription expires
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.router import Router
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionType
from app.models.plan import ServicePlan
from app.integrations.mikrotik import get_mikrotik_client

logger = get_logger(__name__)


class SubscriptionRouterSyncService:
    """Service for syncing subscriptions to MikroTik routers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def sync_subscription_to_router(
        self,
        subscription: Subscription,
        force_create: bool = False
    ) -> Dict[str, Any]:
        """
        Sync a single subscription to its associated router.

        This is the core function that ensures users exist on the router
        with the correct profile/bandwidth settings.

        Args:
            subscription: The subscription to sync
            force_create: If True, recreate user even if exists

        Returns:
            Dict with sync status and any errors
        """
        result = {
            "success": False,
            "subscription_id": subscription.id,
            "action": None,
            "error": None,
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            # Get router
            router = await self._get_router(subscription.router_id)
            if not router:
                result["error"] = f"Router {subscription.router_id} not found"
                return result

            # Get plan for bandwidth settings
            plan = await self._get_plan(subscription.plan_id)
            if not plan:
                result["error"] = f"Plan {subscription.plan_id} not found"
                return result

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
                result["error"] = f"Failed to connect to router {router.ip_address}: {conn_error}"
                return result

            try:
                # Determine action based on subscription status
                if subscription.status == SubscriptionStatus.ACTIVE:
                    # Create or update user on router
                    action_result = await self._ensure_user_on_router(
                        client, connection, subscription, plan, force_create
                    )
                    result["action"] = "create_or_update"
                    result["success"] = action_result["success"]
                    if not action_result["success"]:
                        result["error"] = action_result.get("error")

                elif subscription.status in [
                    SubscriptionStatus.EXPIRED,
                    SubscriptionStatus.SUSPENDED,
                    SubscriptionStatus.CANCELLED
                ]:
                    # Disable user on router and disconnect active session
                    action_result = await self._disable_user_on_router(
                        client, connection, subscription
                    )
                    result["action"] = "disable"
                    result["success"] = action_result["success"]
                    if not action_result["success"]:
                        result["error"] = action_result.get("error")

                # Update sync status in database
                subscription.is_router_synced = result["success"]
                subscription.last_router_sync = datetime.utcnow()
                await self.db.commit()

            finally:
                await client.disconnect(router.ip_address, router.port)

            logger.info(
                f"Subscription {subscription.id} sync: "
                f"action={result['action']}, success={result['success']}"
            )
            return result

        except Exception as e:
            logger.error(f"Subscription sync failed for {subscription.id}: {e}")
            result["error"] = str(e)
            return result

    async def _ensure_user_on_router(
        self,
        client,
        connection,
        subscription: Subscription,
        plan: ServicePlan,
        force_create: bool
    ) -> Dict[str, Any]:
        """Ensure user exists on router with correct settings."""
        result = {"success": False, "error": None}

        try:
            user_type = "hotspot" if subscription.subscription_type == SubscriptionType.HOTSPOT else "pppoe"

            # Check if user already exists
            existing_user = await self._get_user_from_router(
                client, connection, subscription.username, user_type
            )

            # Calculate rate limit string (RouterOS format: download/upload)
            rate_limit = self._calculate_rate_limit(plan)

            if existing_user and not force_create:
                # Update existing user's profile
                await self._update_user_profile(
                    client, connection, subscription.username, user_type, plan, rate_limit
                )
                result["success"] = True
                logger.info(f"Updated existing {user_type} user {subscription.username}")
            else:
                # Delete if exists and force_create
                if existing_user and force_create:
                    resource_path = "/ip/hotspot/user" if user_type == "hotspot" else "/ppp/secret"
                    await client.execute_command(
                        connection, resource_path, method="remove",
                        id=existing_user.get(".id")
                    )

                # Create user with appropriate limits
                if user_type == "hotspot":
                    success = await self._create_hotspot_user_with_limits(
                        client, connection, subscription, plan, rate_limit
                    )
                else:
                    success = await self._create_pppoe_user_with_limits(
                        client, connection, subscription, plan, rate_limit
                    )

                result["success"] = success
                if not success:
                    result["error"] = f"Failed to create {user_type} user"

                logger.info(
                    f"Created {user_type} user {subscription.username} "
                    f"with rate limit {rate_limit}"
                )

            return result

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error ensuring user on router: {e}")
            return result

    async def _create_hotspot_user_with_limits(
        self,
        client,
        connection,
        subscription: Subscription,
        plan: ServicePlan,
        rate_limit: str
    ) -> bool:
        """Create hotspot user with bandwidth and data limits."""
        try:
            # Calculate limits
            limit_uptime = self._calculate_time_limit(plan)
            limit_bytes = self._calculate_data_limit(plan)

            # Build parameters
            params = {
                "name": subscription.username,
                "password": subscription.password,
                "profile": "default",  # Will be overridden by rate-limit
            }

            # Add limits if specified
            if limit_uptime and limit_uptime != "0":
                params["limit-uptime"] = limit_uptime

            if limit_bytes and limit_bytes != "0":
                params["limit-bytes-total"] = limit_bytes

            # Note: For hotspot, rate-limit is typically set via user-profile
            # We'll ensure the profile exists first

            # Ensure profile exists for this plan
            profile_name = f"plan_{plan.id}"
            await self._ensure_hotspot_profile_exists(client, connection, profile_name, rate_limit, plan)
            params["profile"] = profile_name

            await client.execute_command(
                connection, "/ip/hotspot/user", method="add", **params
            )
            return True

        except Exception as e:
            logger.error(f"Failed to create hotspot user: {e}")
            return False

    async def _create_pppoe_user_with_limits(
        self,
        client,
        connection,
        subscription: Subscription,
        plan: ServicePlan,
        rate_limit: str
    ) -> bool:
        """Create PPPoE user with bandwidth limits."""
        try:
            # Ensure PPP profile exists for this plan
            profile_name = f"plan_{plan.id}"
            await self._ensure_ppp_profile_exists(client, connection, profile_name, rate_limit, plan)

            params = {
                "name": subscription.username,
                "password": subscription.password,
                "service": "pppoe",
                "profile": profile_name,
            }

            await client.execute_command(
                connection, "/ppp/secret", method="add", **params
            )
            return True

        except Exception as e:
            logger.error(f"Failed to create PPPoE user: {e}")
            return False

    async def _ensure_hotspot_profile_exists(
        self,
        client,
        connection,
        profile_name: str,
        rate_limit: str,
        plan: ServicePlan
    ) -> bool:
        """Ensure a hotspot user profile exists with correct rate limit."""
        try:
            # Check if profile exists
            profiles = await client.execute_command(
                connection, "/ip/hotspot/user/profile", method="get"
            )

            existing_profile = next(
                (p for p in (profiles or []) if p.get("name") == profile_name),
                None
            )

            if existing_profile:
                # Update rate limit
                await client.execute_command(
                    connection, "/ip/hotspot/user/profile", method="set",
                    id=existing_profile.get(".id"),
                    **{"rate-limit": rate_limit}
                )
            else:
                # Create new profile
                params = {
                    "name": profile_name,
                    "rate-limit": rate_limit,
                    "shared-users": str(plan.concurrent_sessions) if plan.concurrent_sessions else "1",
                }

                if plan.validity_days:
                    # Session timeout based on plan validity
                    params["session-timeout"] = f"{plan.validity_days}d"

                await client.execute_command(
                    connection, "/ip/hotspot/user/profile", method="add", **params
                )

            logger.info(f"Ensured hotspot profile {profile_name} exists with rate {rate_limit}")
            return True

        except Exception as e:
            logger.error(f"Failed to ensure hotspot profile: {e}")
            return False

    async def _ensure_ppp_profile_exists(
        self,
        client,
        connection,
        profile_name: str,
        rate_limit: str,
        plan: ServicePlan
    ) -> bool:
        """Ensure a PPP profile exists with correct rate limit."""
        try:
            # Check if profile exists
            profiles = await client.execute_command(
                connection, "/ppp/profile", method="get"
            )

            existing_profile = next(
                (p for p in (profiles or []) if p.get("name") == profile_name),
                None
            )

            if existing_profile:
                # Update rate limit
                await client.execute_command(
                    connection, "/ppp/profile", method="set",
                    id=existing_profile.get(".id"),
                    **{"rate-limit": rate_limit}
                )
            else:
                # Create new profile with rate limit
                params = {
                    "name": profile_name,
                    "rate-limit": rate_limit,
                    "only-one": "yes" if plan.concurrent_sessions == 1 else "no",
                }

                await client.execute_command(
                    connection, "/ppp/profile", method="add", **params
                )

            logger.info(f"Ensured PPP profile {profile_name} exists with rate {rate_limit}")
            return True

        except Exception as e:
            logger.error(f"Failed to ensure PPP profile: {e}")
            return False

    async def _disable_user_on_router(
        self,
        client,
        connection,
        subscription: Subscription
    ) -> Dict[str, Any]:
        """Disable user on router and disconnect active session."""
        result = {"success": False, "error": None}

        try:
            user_type = "hotspot" if subscription.subscription_type == SubscriptionType.HOTSPOT else "pppoe"

            # First, disconnect any active session
            await self._disconnect_active_session(client, connection, subscription.username, user_type)

            # Then disable the user
            resource_path = '/ip/hotspot/user' if user_type == 'hotspot' else '/ppp/secret'

            try:
                # Find user by name and disable
                users = await client.execute_command(
                    connection, resource_path, method="get"
                )

                user = next((u for u in users if u.get("name") == subscription.username), None)

                if user:
                    await client.execute_command(
                        connection, resource_path, method="set",
                        id=user.get(".id"),
                        disabled="yes"
                    )
                    result["success"] = True
                    logger.info(f"Disabled {user_type} user {subscription.username}")
                else:
                    # User doesn't exist, consider it a success
                    result["success"] = True
                    logger.info(f"User {subscription.username} not found on router (already removed)")

            except Exception as e:
                result["error"] = str(e)
                logger.warning(f"Failed to disable user {subscription.username}: {e}")

            return result

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error disabling user on router: {e}")
            return result

    async def _disconnect_active_session(
        self,
        client,
        connection,
        username: str,
        user_type: str
    ) -> bool:
        """Disconnect user's active session."""
        try:
            if user_type == "hotspot":
                # Get active hotspot sessions
                active = await client.execute_command(
                    connection, "/ip/hotspot/active", method="get"
                )

                for session in (active or []):
                    if session.get("user") == username:
                        await client.execute_command(
                            connection, "/ip/hotspot/active", method="remove",
                            id=session.get(".id")
                        )
                        logger.info(f"Disconnected hotspot session for {username}")
            else:
                # Get active PPPoE sessions
                active = await client.execute_command(
                    connection, "/ppp/active", method="get"
                )

                for session in (active or []):
                    if session.get("name") == username:
                        await client.execute_command(
                            connection, "/ppp/active", method="remove",
                            id=session.get(".id")
                        )
                        logger.info(f"Disconnected PPPoE session for {username}")

            return True

        except Exception as e:
            logger.warning(f"Failed to disconnect session for {username}: {e}")
            return False

    async def _get_user_from_router(
        self,
        client,
        connection,
        username: str,
        user_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get user from router by username."""
        try:
            if user_type == "hotspot":
                users = await client.execute_command(
                    connection, "/ip/hotspot/user", method="get"
                )
            else:
                users = await client.execute_command(
                    connection, "/ppp/secret", method="get"
                )

            return next((u for u in (users or []) if u.get("name") == username), None)

        except Exception as e:
            logger.error(f"Failed to get user from router: {e}")
            return None

    async def _update_user_profile(
        self,
        client,
        connection,
        username: str,
        user_type: str,
        plan: ServicePlan,
        rate_limit: str
    ) -> bool:
        """Update user's profile to match new plan."""
        try:
            profile_name = f"plan_{plan.id}"

            # Ensure profile exists
            if user_type == "hotspot":
                await self._ensure_hotspot_profile_exists(client, connection, profile_name, rate_limit, plan)
                resource_path = '/ip/hotspot/user'
            else:
                await self._ensure_ppp_profile_exists(client, connection, profile_name, rate_limit, plan)
                resource_path = '/ppp/secret'

            # Get user
            users = await client.execute_command(
                connection, resource_path, method="get"
            )

            user = next((u for u in users if u.get("name") == username), None)

            if user:
                await client.execute_command(
                    connection, resource_path, method="set",
                    id=user.get(".id"),
                    profile=profile_name,
                    disabled="no"  # Enable in case it was disabled
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to update user profile: {e}")
            return False

    def _calculate_rate_limit(self, plan: ServicePlan) -> str:
        """Calculate RouterOS rate limit string from plan speeds."""
        # RouterOS format: download/upload
        # Speeds in plan are in Mbps, RouterOS accepts M suffix

        download = plan.download_speed if plan.download_speed else 0
        upload = plan.upload_speed if plan.upload_speed else 0

        if download == 0 and upload == 0:
            return "0/0"  # Unlimited

        return f"{download}M/{upload}M"

    def _calculate_time_limit(self, plan: ServicePlan) -> Optional[str]:
        """Calculate time limit from plan."""
        if plan.time_limit and plan.time_limit > 0:
            # Time limit is in hours
            return f"{plan.time_limit}h"
        return None

    def _calculate_data_limit(self, plan: ServicePlan) -> Optional[str]:
        """Calculate data limit from plan."""
        if plan.data_limit and plan.data_limit > 0:
            # Data limit is in GB, convert to bytes
            bytes_limit = plan.data_limit * 1024 * 1024 * 1024
            return str(int(bytes_limit))
        return None

    async def _get_router(self, router_id: int) -> Optional[Router]:
        """Get router by ID."""
        result = await self.db.execute(
            select(Router).where(Router.id == router_id)
        )
        return result.scalar_one_or_none()

    async def _get_plan(self, plan_id: int) -> Optional[ServicePlan]:
        """Get plan by ID."""
        result = await self.db.execute(
            select(ServicePlan).where(ServicePlan.id == plan_id)
        )
        return result.scalar_one_or_none()

    async def sync_all_unsynced_subscriptions(
        self,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Sync all subscriptions that haven't been synced to their routers.

        This is typically called by a background task.
        """
        results = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "errors": []
        }

        try:
            # Get unsynced active subscriptions
            result = await self.db.execute(
                select(Subscription).where(
                    and_(
                        Subscription.is_router_synced == False,  # noqa: E712
                        Subscription.status == SubscriptionStatus.ACTIVE
                    )
                ).limit(limit)
            )
            unsynced = result.scalars().all()

            results["total"] = len(unsynced)

            for subscription in unsynced:
                sync_result = await self.sync_subscription_to_router(subscription)

                if sync_result["success"]:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({
                        "subscription_id": subscription.id,
                        "error": sync_result.get("error")
                    })

            logger.info(
                f"Sync batch complete: {results['success']}/{results['total']} successful"
            )
            return results

        except Exception as e:
            logger.error(f"Batch sync failed: {e}")
            results["errors"].append({"error": str(e)})
            return results

    async def sync_router_subscriptions(
        self,
        router_id: int
    ) -> Dict[str, Any]:
        """
        Sync all subscriptions for a specific router.

        Useful after router provisioning or reconnection.
        """
        results = {
            "router_id": router_id,
            "total": 0,
            "success": 0,
            "failed": 0,
            "errors": []
        }

        try:
            # Get all active subscriptions for this router
            result = await self.db.execute(
                select(Subscription).where(
                    and_(
                        Subscription.router_id == router_id,
                        Subscription.status == SubscriptionStatus.ACTIVE
                    )
                )
            )
            subscriptions = result.scalars().all()

            results["total"] = len(subscriptions)

            for subscription in subscriptions:
                sync_result = await self.sync_subscription_to_router(
                    subscription, force_create=True
                )

                if sync_result["success"]:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({
                        "subscription_id": subscription.id,
                        "error": sync_result.get("error")
                    })

            logger.info(
                f"Router {router_id} sync complete: "
                f"{results['success']}/{results['total']} successful"
            )
            return results

        except Exception as e:
            logger.error(f"Router sync failed: {e}")
            results["errors"].append({"error": str(e)})
            return results
