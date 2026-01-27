"""
Router reprovisioning service.
Handles configuration updates via API without requiring bootstrap command.
"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.router import Router
from app.core.encryption import get_credential_encryption


logger = logging.getLogger(__name__)


async def store_router_credentials(
    db: AsyncSession,
    router_id: int,
    username: str,
    password: str,
    bootstrap_completed: bool = True
) -> Router:
    """Store encrypted API credentials after successful bootstrap.
    
    Args:
        db: Database session
        router_id: Router ID
        username: API username
        password: API password
        bootstrap_completed: Whether bootstrap script executed successfully
        
    Returns:
        Updated router instance
    """
    # Get router
    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()
    
    if not router:
        raise ValueError(f"Router {router_id} not found")
    
    # Encrypt credentials
    encryption = get_credential_encryption()
    encrypted_creds = encryption.encrypt_credentials(username, password)
    
    # Update router
    router.api_credentials_encrypted = encrypted_creds
    router.bootstrap_completed = bootstrap_completed
    router.provisioning_status = 'provisioned' if bootstrap_completed else 'pending'
    router.last_provisioned_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(router)
    
    logger.info(f"Stored credentials for router {router_id} (bootstrap_completed={bootstrap_completed})")
    return router


async def get_router_credentials(db: AsyncSession, router_id: int) -> Optional[dict]:
    """Retrieve decrypted router credentials.
    
    Args:
        db: Database session
        router_id: Router ID
        
    Returns:
        Dict with 'username' and 'password' or None if not stored
    """
    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()
    
    if not router or not router.api_credentials_encrypted:
        return None
    
    encryption = get_credential_encryption()
    try:
        credentials = encryption.decrypt_credentials(router.api_credentials_encrypted)
        return credentials
    except Exception as e:
        logger.error(f"Failed to decrypt credentials for router {router_id}: {e}")
        return None


async def can_use_direct_api(db: AsyncSession, router_id: int) -> bool:
    """Check if router can be reprovisioned via direct API.
    
    Args:
        db: Database session
        router_id: Router ID
        
    Returns:
        True if router has stored credentials and bootstrap completed
    """
    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()
    
    if not router:
        return False
    
    return (
        router.bootstrap_completed and
        router.api_credentials_encrypted is not None and
        router.provisioning_status == 'provisioned'
    )


async def mark_provisioning_failed(db: AsyncSession, router_id: int, error: str) -> Router:
    """Mark router provisioning as failed.
    
    Args:
        db: Database session
        router_id: Router ID
        error: Error message
        
    Returns:
        Updated router instance
    """
    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()
    
    if not router:
        raise ValueError(f"Router {router_id} not found")
    
    router.provisioning_status = 'failed'
    router.notes = f"Provisioning failed: {error}\n{router.notes or ''}"
    
    await db.commit()
    await db.refresh(router)
    
    logger.error(f"Marked router {router_id} provisioning as failed: {error}")
    return router
