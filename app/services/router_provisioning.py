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
from app.core.config import settings


logger = logging.getLogger(__name__)


def get_default_api_credentials() -> dict:
    """Get default API credentials from environment settings.

    These credentials are created by the bootstrap script on the router
    and should be used for all API communications with provisioned routers.

    Returns:
        Dict with 'username' and 'password' from env variables.
    """
    return {
        "username": settings.mikrotik_api_username,
        "password": settings.mikrotik_api_password,
    }


async def store_router_credentials(
    db: AsyncSession,
    router_id: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
    bootstrap_completed: bool = True
) -> Router:
    """Store encrypted API credentials after successful bootstrap.

    If username/password not provided, uses default API credentials from
    environment settings (MIKROTIK_API_USERNAME, MIKROTIK_API_PASSWORD).

    Args:
        db: Database session
        router_id: Router ID
        username: API username (optional, defaults to env settings)
        password: API password (optional, defaults to env settings)
        bootstrap_completed: Whether bootstrap script executed successfully

    Returns:
        Updated router instance
    """
    # Use default API credentials if not provided
    if username is None:
        username = settings.mikrotik_api_username
    if password is None:
        password = settings.mikrotik_api_password
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

    First tries to decrypt stored credentials from DB.
    Falls back to env settings if not stored or decryption fails.

    Args:
        db: Database session
        router_id: Router ID

    Returns:
        Dict with 'username' and 'password' (never None - uses fallback)
    """
    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()

    if not router:
        return None

    # Try to get from encrypted storage first
    if router.api_credentials_encrypted:
        encryption = get_credential_encryption()
        try:
            credentials = encryption.decrypt_credentials(router.api_credentials_encrypted)
            return credentials
        except Exception as e:
            logger.error(f"Failed to decrypt credentials for router {router_id}: {e}")
            # Fall through to use env settings

    # Fallback: use credentials from env settings
    logger.info(f"Using env credentials for router {router_id} (no encrypted creds stored)")
    return get_default_api_credentials()


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


async def store_scanned_config(
    db: AsyncSession,
    router_id: int,
    interfaces: list,
    services: list,
    network_config: dict,
    system_info: dict
) -> Router:
    """Store scanned configuration data in the router's config JSON field.

    This avoids re-scanning once provisioning is complete.

    Args:
        db: Database session
        router_id: Router ID
        interfaces: List of interface names (e.g., ["ether1", "ether2", ...])
        services: List of service status dicts (e.g., [{"name": "hotspot", "active": True}, ...])
        network_config: Network configuration dict
        system_info: System information dict

    Returns:
        Updated router instance
    """
    import json

    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()

    if not router:
        raise ValueError(f"Router {router_id} not found")

    # Build scanned config data
    scanned_data = {
        "interfaces": interfaces,
        "services": services,
        "network_config": network_config,
        "system_info": system_info,
        "last_scanned_at": datetime.utcnow().isoformat()
    }

    # Merge with existing config or create new
    existing_config = {}
    if router.config:
        try:
            existing_config = json.loads(router.config) if isinstance(router.config, str) else router.config
        except (json.JSONDecodeError, TypeError):
            existing_config = {}

    existing_config["scanned_data"] = scanned_data
    router.config = json.dumps(existing_config)

    # Update system info fields on the router model itself
    if system_info:
        if system_info.get("version"):
            router.routeros_version = system_info.get("version")
        if system_info.get("board_name"):
            router.board_name = system_info.get("board_name")
        if system_info.get("architecture"):
            router.architecture = system_info.get("architecture")
        if system_info.get("cpu_count"):
            router.cpu_count = system_info.get("cpu_count")

    await db.commit()
    await db.refresh(router)

    logger.info(f"Stored scanned config for router {router_id}: {len(interfaces)} interfaces, {len(services)} services")
    return router


async def get_scanned_config(db: AsyncSession, router_id: int) -> Optional[dict]:
    """Retrieve previously scanned configuration data for a router.

    Args:
        db: Database session
        router_id: Router ID

    Returns:
        Dict with scanned data or None if not available
    """
    import json

    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()

    if not router or not router.config:
        return None

    try:
        config = json.loads(router.config) if isinstance(router.config, str) else router.config
        return config.get("scanned_data")
    except (json.JSONDecodeError, TypeError):
        return None


async def mark_provisioning_complete(
    db: AsyncSession,
    router_id: int,
    service_type: str = None
) -> Router:
    """Mark router provisioning as complete after successful workflow.

    Args:
        db: Database session
        router_id: Router ID
        service_type: Optional service type that was configured (hotspot, pppoe, both)

    Returns:
        Updated router instance
    """
    import json

    result = await db.execute(select(Router).where(Router.id == router_id))
    router = result.scalar_one_or_none()

    if not router:
        raise ValueError(f"Router {router_id} not found")

    # Update provisioning status
    router.provisioning_status = 'provisioned'
    router.bootstrap_completed = True
    router.last_provisioned_at = datetime.utcnow()

    # Store service type in config
    if service_type:
        existing_config = {}
        if router.config:
            try:
                existing_config = json.loads(router.config) if isinstance(router.config, str) else router.config
            except (json.JSONDecodeError, TypeError):
                existing_config = {}

        existing_config["provisioned_service_type"] = service_type
        existing_config["provisioned_at"] = datetime.utcnow().isoformat()
        router.config = json.dumps(existing_config)

    await db.commit()
    await db.refresh(router)

    logger.info(f"Marked router {router_id} provisioning as complete (service_type={service_type})")
    return router


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
