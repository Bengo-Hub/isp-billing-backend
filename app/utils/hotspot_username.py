"""Hotspot username generation utility.

Generates unique usernames for hotspot users when they purchase packages.
Username format: PREFIX + INCREMENTAL_NUMBER (e.g., C001, C002, H0001)
Password format: Random 3-digit number
"""

import secrets
from typing import Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import OrganizationSettings


async def generate_hotspot_credentials(
    db: AsyncSession,
    organization_id: int,
    password_length: int = 3
) -> Tuple[str, str]:
    """
    Generate unique hotspot username and password for a new user.

    Args:
        db: Database session
        organization_id: Organization ID to get settings from
        password_length: Length of numeric password (default: 3 digits)

    Returns:
        Tuple of (username, password)
        Example: ("C029", "865")
    """
    # Get organization settings
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization_id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings if not exists
        settings = OrganizationSettings(
            organization_id=organization_id,
            hotspot_username_prefix="C",
            hotspot_username_counter=1,
        )
        db.add(settings)
        await db.flush()

    # Get current counter and prefix
    prefix = settings.hotspot_username_prefix
    counter = settings.hotspot_username_counter

    # Generate username (e.g., C001, C002, H0001)
    # Pad with zeros based on counter magnitude
    if counter < 1000:
        username = f"{prefix}{counter:03d}"  # C001, C099, C999
    elif counter < 10000:
        username = f"{prefix}{counter:04d}"  # C1000, C9999
    else:
        username = f"{prefix}{counter:05d}"  # C10000+

    # Generate random numeric password (e.g., 865, 123, 999)
    password = ''.join(str(secrets.randbelow(10)) for _ in range(password_length))

    # Increment counter for next user
    settings.hotspot_username_counter = counter + 1
    await db.commit()

    return username, password


async def get_next_username_preview(
    db: AsyncSession,
    organization_id: int
) -> str:
    """
    Preview what the next generated username will be (without incrementing).

    Args:
        db: Database session
        organization_id: Organization ID

    Returns:
        Preview of next username (e.g., "C030")
    """
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization_id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        return "C001"

    prefix = settings.hotspot_username_prefix
    counter = settings.hotspot_username_counter

    if counter < 1000:
        return f"{prefix}{counter:03d}"
    elif counter < 10000:
        return f"{prefix}{counter:04d}"
    else:
        return f"{prefix}{counter:05d}"


async def reset_username_counter(
    db: AsyncSession,
    organization_id: int,
    new_counter: int = 1
) -> bool:
    """
    Reset the username counter for an organization.

    Args:
        db: Database session
        organization_id: Organization ID
        new_counter: New counter value (default: 1)

    Returns:
        True if successful, False otherwise
    """
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization_id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        return False

    settings.hotspot_username_counter = new_counter
    await db.commit()
    return True


async def update_username_prefix(
    db: AsyncSession,
    organization_id: int,
    new_prefix: str
) -> bool:
    """
    Update the username prefix for an organization.

    Args:
        db: Database session
        organization_id: Organization ID
        new_prefix: New prefix (e.g., "H", "NET")

    Returns:
        True if successful, False otherwise
    """
    result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization_id
        )
    )
    settings = result.scalar_one_or_none()

    if not settings:
        return False

    settings.hotspot_username_prefix = new_prefix
    await db.commit()
    return True
