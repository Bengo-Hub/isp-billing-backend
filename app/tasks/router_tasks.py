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
from app.services.router_service import RouterService

logger = get_logger(__name__)


@celery_app.task(bind=True)
def sync_router_status(self):
    """Sync router status and update database."""
    logger.info("Starting router status sync")
    
    try:
        async def _sync_routers():
            async with AsyncSessionLocal() as db:
                router_service = RouterService(db)
                
                # Get all active routers
                result = await db.execute(
                    select(Router).where(Router.is_active == True)
                )
                routers = result.scalars().all()
                
                synced_count = 0
                for router in routers:
                    try:
                        # Check router connectivity
                        is_online = await router_service.check_router_connectivity(router.id)
                        
                        if is_online:
                            router.status = RouterStatus.ONLINE
                            router.last_seen = datetime.utcnow()
                        else:
                            router.status = RouterStatus.OFFLINE
                        
                        synced_count += 1
                    except Exception as e:
                        logger.error(f"Failed to sync router {router.id}: {e}")
                        router.status = RouterStatus.OFFLINE
                
                await db.commit()
                return synced_count
        
        import asyncio
        synced_count = asyncio.run(_sync_routers())
        
        logger.info(f"Router status sync completed. Synced {synced_count} routers")
        return {
            "status": "success", 
            "synced_count": synced_count
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