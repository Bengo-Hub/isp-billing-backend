"""Router-related Celery tasks."""

from datetime import datetime, timedelta
from typing import List, Dict, Any

from celery import current_task
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.router import Router, RouterStatus
from app.modules.routers import RouterService

logger = get_logger(__name__)


@celery_app.task(bind=True)
def sync_router_status(self):
    """Sync router status using agent poll data.

    For routers with the polling agent installed, status is determined
    by the last poll timestamp (no direct connection needed).
    For routers without the agent, falls back to direct connectivity check.
    """
    logger.info("Starting router status sync")

    try:
        async def _sync_routers():
            async with AsyncSessionLocal() as db:
                from app.core.config import settings

                result = await db.execute(
                    select(Router).where(Router.is_active == True)
                )
                routers = result.scalars().all()

                synced_count = 0
                online_count = 0
                for router in routers:
                    try:
                        if router.agent_installed and router.last_poll_at:
                            # Agent-based status: online if polled within threshold
                            elapsed = (datetime.utcnow() - router.last_poll_at).total_seconds()
                            threshold = router.agent_poll_interval * settings.agent_offline_threshold_multiplier
                            if elapsed < threshold:
                                router.status = RouterStatus.ONLINE
                                online_count += 1
                            else:
                                router.status = RouterStatus.OFFLINE
                        else:
                            # Fallback: direct connectivity check
                            router_service = RouterService(db)
                            is_online = await router_service.check_router_connectivity(router.id)
                            if is_online:
                                router.status = RouterStatus.ONLINE
                                router.last_seen = datetime.utcnow()
                                online_count += 1
                            else:
                                router.status = RouterStatus.OFFLINE

                        synced_count += 1
                    except Exception as e:
                        logger.error(f"Failed to sync router {router.id}: {e}")
                        router.status = RouterStatus.OFFLINE

                await db.commit()
                return synced_count, online_count

        import asyncio
        synced_count, online_count = asyncio.run(_sync_routers())

        logger.info(
            f"Router status sync completed. "
            f"Synced {synced_count} routers ({online_count} online)"
        )
        return {
            "status": "success",
            "synced_count": synced_count,
            "online_count": online_count,
        }
    except Exception as exc:
        logger.error(f"Router status sync failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def sync_router_users(self, router_id: int):
    """Sync users from a specific router."""
    logger.info(f"Syncing users from router {router_id}")
    
    try:
        async def _sync_router_users():
            async with AsyncSessionLocal() as db:
                router_service = RouterService(db)
                
                # Get router
                router = await router_service.get_by_id(router_id)
                if not router:
                    return None
                
                # Sync users from router
                synced_users = await router_service.sync_router_users(router_id)
                
                return synced_users
        
        import asyncio
        synced_users = asyncio.run(_sync_router_users())
        
        if synced_users is not None:
            logger.info(f"Router users sync completed for router {router_id}")
            return {
                "status": "success", 
                "router_id": router_id,
                "synced_users": synced_users
            }
        else:
            logger.warning(f"Router {router_id} not found for user sync")
            return {
                "status": "failed", 
                "router_id": router_id,
                "error": "Router not found"
            }
    except Exception as exc:
        logger.error(f"Router users sync failed for router {router_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def backup_router_config(self, router_id: int):
    """Backup router configuration."""
    logger.info(f"Backing up configuration for router {router_id}")
    
    try:
        async def _backup_config():
            async with AsyncSessionLocal() as db:
                router_service = RouterService(db)
                
                # Get router
                router = await router_service.get_by_id(router_id)
                if not router:
                    return None
                
                # Backup configuration
                config = await router_service.backup_router_config(router_id)
                
                return config
        
        import asyncio
        config = asyncio.run(_backup_config())
        
        if config is not None:
            logger.info(f"Router configuration backup completed for router {router_id}")
            return {
                "status": "success", 
                "router_id": router_id,
                "config_size": len(config) if config else 0
            }
        else:
            logger.warning(f"Router {router_id} not found for config backup")
            return {
                "status": "failed", 
                "router_id": router_id,
                "error": "Router not found"
            }
    except Exception as exc:
        logger.error(f"Router config backup failed for router {router_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def update_router_firmware(self, router_id: int):
    """Update router firmware."""
    logger.info(f"Updating firmware for router {router_id}")
    
    try:
        async def _update_firmware():
            async with AsyncSessionLocal() as db:
                router_service = RouterService(db)
                
                # Get router
                router = await router_service.get_by_id(router_id)
                if not router:
                    return None
                
                # Update firmware
                result = await router_service.update_router_firmware(router_id)
                
                return result
        
        import asyncio
        result = asyncio.run(_update_firmware())
        
        if result is not None:
            logger.info(f"Router firmware update completed for router {router_id}")
            return {
                "status": "success", 
                "router_id": router_id,
                "result": result
            }
        else:
            logger.warning(f"Router {router_id} not found for firmware update")
            return {
                "status": "failed", 
                "router_id": router_id,
                "error": "Router not found"
            }
    except Exception as exc:
        logger.error(f"Router firmware update failed for router {router_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def cleanup_old_router_logs(self, days_old: int = 30):
    """Clean up old router logs."""
    logger.info(f"Cleaning up router logs older than {days_old} days")
    
    try:
        async def _cleanup_logs():
            async with AsyncSessionLocal() as db:
                from app.models.router import RouterLog
                
                # Get old logs
                cutoff_date = datetime.utcnow() - timedelta(days=days_old)
                result = await db.execute(
                    select(RouterLog).where(RouterLog.created_at < cutoff_date)
                )
                old_logs = result.scalars().all()
                
                cleaned_count = 0
                for log in old_logs:
                    await db.delete(log)
                    cleaned_count += 1
                
                await db.commit()
                return cleaned_count
        
        import asyncio
        cleaned_count = asyncio.run(_cleanup_logs())
        
        logger.info(f"Router logs cleanup completed. Cleaned {cleaned_count} logs")
        return {
            "status": "success", 
            "cleaned_count": cleaned_count
        }
    except Exception as exc:
        logger.error(f"Router logs cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def cleanup_old_router_backups(self, days_old: int = 2):
    """Churn router backups older than ``days_old`` days (default 2).

    Deletes the RouterBackup rows — and with them the stored .backup blobs — so
    backups don't accumulate. Runs daily via beat.
    """
    logger.info(f"Cleaning up router backups older than {days_old} days")

    try:
        async def _cleanup_backups():
            async with AsyncSessionLocal() as db:
                from app.models.router import RouterBackup

                cutoff = datetime.utcnow() - timedelta(days=days_old)
                result = await db.execute(
                    select(RouterBackup).where(RouterBackup.created_at < cutoff)
                )
                old = result.scalars().all()
                count = 0
                for b in old:
                    await db.delete(b)
                    count += 1
                await db.commit()
                return count

        import asyncio
        cleaned = asyncio.run(_cleanup_backups())

        logger.info(f"Router backup cleanup completed. Removed {cleaned} backups")
        return {"status": "success", "cleaned_count": cleaned}
    except Exception as exc:
        logger.error(f"Router backup cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def cleanup_expired_commands(self):
    """Clean up expired router agent commands and reset stale sent commands."""
    logger.info("Starting expired command cleanup")

    try:
        async def _cleanup():
            async with AsyncSessionLocal() as db:
                from app.services.router_agent import RouterAgentService
                agent_service = RouterAgentService(db)
                expired = await agent_service.cleanup_expired_commands()
                stale = await agent_service.reset_stale_sent_commands()
                return expired, stale

        import asyncio
        expired, stale = asyncio.run(_cleanup())

        logger.info(
            f"Command cleanup completed: {expired} expired, {stale} stale reset"
        )
        return {
            "status": "success",
            "expired_count": expired,
            "stale_reset_count": stale,
        }
    except Exception as exc:
        logger.error(f"Command cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)