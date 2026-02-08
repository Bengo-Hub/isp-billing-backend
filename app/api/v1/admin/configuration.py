"""Configuration management API endpoints."""

import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.models.configuration import Configuration, ConfigType
from app.modules.system import ConfigurationService
from app.schemas.configuration import (
    ConfigurationResponse,
    ConfigurationCreate,
    ConfigurationUpdate,
    ConfigurationList
)

router = APIRouter()

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "static" / "uploads" / "logos"
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB


@router.get("/", response_model=ConfigurationList)
async def get_configurations(
    category: Optional[str] = None,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db)
) -> ConfigurationList:
    """Get all configurations, optionally filtered by category.

    PLATFORM_OWNER users get platform-level configs (organization_id=None).
    ISP_ADMIN users get their organization's configs.
    """
    try:
        config_service = ConfigurationService(db)
        # Extract organization_id from current user
        organization_id = current_user.organization_id
        configs = await config_service.get_all_configs(
            category=category,
            organization_id=organization_id
        )

        return ConfigurationList(
            configurations=configs,
            total=len(configs)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configurations: {str(e)}"
        )


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Upload organization logo image.

    Saves the file and updates the system.logo_url config setting.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}"
        )

    contents = await file.read()
    if len(contents) > MAX_LOGO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 2MB."
        )

    # Ensure upload directory exists
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    ext = Path(file.filename).suffix if file.filename else ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / filename

    with open(file_path, "wb") as f:
        f.write(contents)

    logo_url = f"/uploads/logos/{filename}"

    # Update config setting
    config_service = ConfigurationService(db)
    organization_id = current_user.organization_id
    await config_service.set_config(
        key="system.logo_url",
        value=logo_url,
        category="system",
        organization_id=organization_id,
    )

    return {"logo_url": logo_url}


@router.delete("/logo", status_code=status.HTTP_200_OK)
async def delete_logo(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Delete organization logo and reset to default."""
    config_service = ConfigurationService(db)
    organization_id = current_user.organization_id

    # Get current logo URL to delete the file
    current_url = await config_service.get_config(
        key="system.logo_url",
        organization_id=organization_id,
    )
    if current_url and isinstance(current_url, str) and current_url.startswith("/uploads/logos/"):
        file_path = Path(__file__).resolve().parents[3] / "static" / current_url.lstrip("/")
        if file_path.exists():
            file_path.unlink()

    # Reset config to default
    await config_service.set_config(
        key="system.logo_url",
        value="/images/logo/logo.png",
        category="system",
        organization_id=organization_id,
    )

    return {"message": "Logo deleted", "logo_url": "/images/logo/logo.png"}


@router.get("/{key}", response_model=ConfigurationResponse)
async def get_configuration(
    key: str,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db)
) -> ConfigurationResponse:
    """Get configuration by key.

    PLATFORM_OWNER users get platform-level configs (organization_id=None).
    ISP_ADMIN users get their organization's configs.
    """
    try:
        config_service = ConfigurationService(db)
        # Extract organization_id from current user
        organization_id = current_user.organization_id
        value = await config_service.get_config(
            key=key,
            organization_id=organization_id
        )

        if value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Configuration not found"
            )

        return ConfigurationResponse(key=key, value=value)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration: {str(e)}"
        )


@router.post("/", response_model=ConfigurationResponse)
async def create_configuration(
    config_data: ConfigurationCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db)
) -> ConfigurationResponse:
    """Create or update configuration.

    PLATFORM_OWNER users create platform-level configs (organization_id=None).
    ISP_ADMIN users create configs for their organization.
    """
    try:
        config_service = ConfigurationService(db)
        # Extract organization_id from current user
        organization_id = current_user.organization_id
        config = await config_service.set_config(
            key=config_data.key,
            value=config_data.value,
            config_type=config_data.config_type,
            description=config_data.description,
            is_encrypted=config_data.is_encrypted,
            is_sensitive=config_data.is_sensitive,
            category=config_data.category,
            organization_id=organization_id
        )

        # Return the complete configuration object with all fields
        return ConfigurationResponse.model_validate(config)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create configuration: {str(e)}"
        )


@router.put("/{key}", response_model=ConfigurationResponse)
async def update_configuration(
    key: str,
    config_data: ConfigurationUpdate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db)
) -> ConfigurationResponse:
    """Update configuration.

    PLATFORM_OWNER users update platform-level configs (organization_id=None).
    ISP_ADMIN users update configs for their organization.
    """
    try:
        config_service = ConfigurationService(db)
        # Extract organization_id from current user
        organization_id = current_user.organization_id

        # Get existing config to preserve some fields
        existing_value = await config_service.get_config(
            key=key,
            organization_id=organization_id
        )
        if existing_value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Configuration not found"
            )

        config = await config_service.set_config(
            key=key,
            value=config_data.value if config_data.value is not None else existing_value,
            config_type=config_data.config_type,
            description=config_data.description,
            is_encrypted=config_data.is_encrypted,
            is_sensitive=config_data.is_sensitive,
            category=config_data.category,
            organization_id=organization_id
        )

        # Return the complete configuration object with all fields
        return ConfigurationResponse.model_validate(config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {str(e)}"
        )


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_configuration(
    key: str,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db)
) -> None:
    """Delete configuration.

    PLATFORM_OWNER users delete platform-level configs (organization_id=None).
    ISP_ADMIN users delete configs from their organization.
    """
    try:
        config_service = ConfigurationService(db)
        # Extract organization_id from current user
        organization_id = current_user.organization_id
        success = await config_service.delete_config(
            key=key,
            organization_id=organization_id
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Configuration not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete configuration: {str(e)}"
        )
