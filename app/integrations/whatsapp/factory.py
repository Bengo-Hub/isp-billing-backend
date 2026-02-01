"""WhatsApp provider factory for creating provider instances.

This factory pattern allows for:
- Dynamic provider selection based on configuration
- Provider registration via decorators
- Automatic fallback to default provider
"""

import logging
from typing import Any, Callable, Dict, Optional, Type

from app.core.logging import get_logger
from .base import WhatsAppProviderInterface, WhatsAppProviderConfig

logger = get_logger(__name__)


class WhatsAppProviderType:
    """WhatsApp provider type enumeration."""
    APIWAP = "apiwap"
    TWILIO_WHATSAPP = "twilio_whatsapp"
    CUSTOM = "custom"


class WhatsAppProviderFactory:
    """Factory for creating WhatsApp provider instances.

    Usage:
        # Create a provider instance
        provider = await WhatsAppProviderFactory.create(
            WhatsAppProviderType.APIWAP,
            credentials={"api_key": "..."}
        )
    """

    _providers: Dict[str, Type[WhatsAppProviderInterface]] = {}
    _default_provider: str = WhatsAppProviderType.APIWAP

    @classmethod
    def register(cls, provider_type: str) -> Callable:
        """Decorator to register a provider class.

        Args:
            provider_type: Provider type to register

        Returns:
            Decorator function
        """
        def decorator(provider_class: Type[WhatsAppProviderInterface]) -> Type[WhatsAppProviderInterface]:
            cls._providers[provider_type] = provider_class
            logger.debug(f"Registered WhatsApp provider: {provider_type}")
            return provider_class
        return decorator

    @classmethod
    def set_default(cls, provider_type: str) -> None:
        """Set the default provider type.

        Args:
            provider_type: Provider type to set as default
        """
        if provider_type not in cls._providers:
            raise ValueError(f"Provider {provider_type} is not registered")
        cls._default_provider = provider_type
        logger.info(f"Set default WhatsApp provider to: {provider_type}")

    @classmethod
    async def create(
        cls,
        provider_type: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        is_default: bool = False,
        default_country_code: str = "+254",
        **kwargs,
    ) -> WhatsAppProviderInterface:
        """Create a WhatsApp provider instance.

        Args:
            provider_type: Provider type (uses default if not specified)
            credentials: Provider credentials
            is_active: Whether the provider is active
            is_default: Whether this is the default provider
            default_country_code: Default country code for phone formatting
            **kwargs: Additional config options

        Returns:
            WhatsAppProviderInterface instance

        Raises:
            ValueError: If provider type is not registered
        """
        # Use default provider if not specified
        provider_type = provider_type or cls._default_provider

        # Get provider class
        provider_class = cls._providers.get(provider_type)
        if provider_class is None:
            # Try to load the provider dynamically
            cls._load_provider(provider_type)
            provider_class = cls._providers.get(provider_type)

            if provider_class is None:
                raise ValueError(f"Unknown WhatsApp provider type: {provider_type}")

        # Create config
        config = WhatsAppProviderConfig(
            provider_type=provider_type,
            credentials=credentials or {},
            is_active=is_active,
            is_default=is_default,
            default_country_code=default_country_code,
            **kwargs,
        )

        # Create and return provider instance
        return provider_class(config)

    @classmethod
    def _load_provider(cls, provider_type: str) -> None:
        """Dynamically load a provider module.

        Args:
            provider_type: Provider type to load
        """
        try:
            if provider_type == WhatsAppProviderType.APIWAP:
                from .apiwap_provider import APIWAPWhatsAppProvider
                cls._providers[provider_type] = APIWAPWhatsAppProvider

            elif provider_type == WhatsAppProviderType.TWILIO_WHATSAPP:
                # Placeholder for Twilio WhatsApp provider
                logger.warning(f"Twilio WhatsApp provider not yet implemented")

            elif provider_type == WhatsAppProviderType.CUSTOM:
                # Custom providers should be registered manually
                logger.warning(f"Custom provider must be registered manually")

        except ImportError as e:
            logger.error(f"Failed to load WhatsApp provider {provider_type}: {e}")

    @classmethod
    def get_available_providers(cls) -> Dict[str, bool]:
        """Get list of available providers and their status.

        Returns:
            Dictionary of provider names and availability
        """
        # Load all providers
        for provider_type in [WhatsAppProviderType.APIWAP, WhatsAppProviderType.TWILIO_WHATSAPP]:
            if provider_type not in cls._providers:
                cls._load_provider(provider_type)

        return {
            provider_type: provider_type in cls._providers
            for provider_type in [WhatsAppProviderType.APIWAP, WhatsAppProviderType.TWILIO_WHATSAPP, WhatsAppProviderType.CUSTOM]
        }

    @classmethod
    async def create_from_config(
        cls,
        config_dict: Dict[str, Any],
    ) -> WhatsAppProviderInterface:
        """Create a provider from a configuration dictionary.

        Args:
            config_dict: Configuration dictionary with provider settings

        Returns:
            WhatsAppProviderInterface instance
        """
        provider_type = config_dict.get("provider_type", WhatsAppProviderType.APIWAP)

        return await cls.create(
            provider_type=provider_type,
            credentials=config_dict.get("credentials", {}),
            is_active=config_dict.get("is_active", True),
            is_default=config_dict.get("is_default", False),
            default_country_code=config_dict.get("default_country_code", "+254"),
        )


# Auto-register providers
def _register_providers():
    """Register all built-in providers."""
    try:
        from .apiwap_provider import APIWAPWhatsAppProvider
        WhatsAppProviderFactory._providers[WhatsAppProviderType.APIWAP] = APIWAPWhatsAppProvider
    except ImportError:
        pass


# Register providers on module load
_register_providers()
