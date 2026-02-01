"""Configuration management API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
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
