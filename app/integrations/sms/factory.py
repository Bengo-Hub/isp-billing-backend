"""SMS provider factory for creating provider instances.

This factory pattern allows for:
- Dynamic provider selection based on configuration
- Provider registration via decorators
- Automatic fallback to default provider
"""

import logging
from typing import Any, Callable, Dict, Optional, Type

from app.core.logging import get_logger
from app.models.sms_credit import SMSProviderType
from .base import SMSProviderInterface, SMSProviderConfig

logger = get_logger(__name__)


class SMSProviderFactory:
    """Factory for creating SMS provider instances.
    
    Usage:
        # Register a provider
        @SMSProviderFactory.register(SMSProviderType.TWILIO)
        class TwilioProvider(SMSProviderInterface):
            ...
        
        # Create a provider instance
        provider = await SMSProviderFactory.create(
            SMSProviderType.TWILIO,
            credentials={"account_sid": "...", "auth_token": "...", "from_number": "..."}
        )
    """
    
    _providers: Dict[SMSProviderType, Type[SMSProviderInterface]] = {}
    _default_provider: SMSProviderType = SMSProviderType.TWILIO
    
    @classmethod
    def register(cls, provider_type: SMSProviderType) -> Callable:
        """Decorator to register a provider class.
        
        Args:
            provider_type: Provider type to register
            
        Returns:
            Decorator function
        """
        def decorator(provider_class: Type[SMSProviderInterface]) -> Type[SMSProviderInterface]:
            cls._providers[provider_type] = provider_class
            logger.debug(f"Registered SMS provider: {provider_type.value}")
            return provider_class
        return decorator
    
    @classmethod
    def set_default(cls, provider_type: SMSProviderType) -> None:
        """Set the default provider type.
        
        Args:
            provider_type: Provider type to set as default
        """
        if provider_type not in cls._providers:
            raise ValueError(f"Provider {provider_type.value} is not registered")
        cls._default_provider = provider_type
        logger.info(f"Set default SMS provider to: {provider_type.value}")
    
    @classmethod
    async def create(
        cls,
        provider_type: Optional[SMSProviderType] = None,
        credentials: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        is_default: bool = False,
        default_country_code: str = "+254",
        **kwargs,
    ) -> SMSProviderInterface:
        """Create an SMS provider instance.
        
        Args:
            provider_type: Provider type (uses default if not specified)
            credentials: Provider credentials
            is_active: Whether the provider is active
            is_default: Whether this is the default provider
            default_country_code: Default country code for phone formatting
            **kwargs: Additional config options
            
        Returns:
            SMSProviderInterface instance
            
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
                raise ValueError(f"Unknown SMS provider type: {provider_type.value}")
        
        # Create config
        config = SMSProviderConfig(
            provider_type=provider_type.value,
            credentials=credentials or {},
            is_active=is_active,
            is_default=is_default,
            default_country_code=default_country_code,
            **kwargs,
        )
        
        # Create and return provider instance
        return provider_class(config)
    
    @classmethod
    def _load_provider(cls, provider_type: SMSProviderType) -> None:
        """Dynamically load a provider module.
        
        Args:
            provider_type: Provider type to load
        """
        try:
            if provider_type == SMSProviderType.TWILIO:
                from .twilio_provider import TwilioSMSProvider
                cls._providers[provider_type] = TwilioSMSProvider
                
            elif provider_type == SMSProviderType.AFRICASTALKING:
                from .africastalking_provider import AfricasTalkingSMSProvider
                cls._providers[provider_type] = AfricasTalkingSMSProvider
                
            elif provider_type == SMSProviderType.SMS_GLOBAL:
                # Placeholder for SMS Global provider
                logger.warning(f"SMS Global provider not yet implemented")
                
            elif provider_type == SMSProviderType.CUSTOM:
                # Custom providers should be registered manually
                logger.warning(f"Custom provider must be registered manually")
                
        except ImportError as e:
            logger.error(f"Failed to load SMS provider {provider_type.value}: {e}")
    
    @classmethod
    def get_available_providers(cls) -> Dict[str, bool]:
        """Get list of available providers and their status.
        
        Returns:
            Dictionary of provider names and availability
        """
        # Load all providers
        for provider_type in SMSProviderType:
            if provider_type not in cls._providers:
                cls._load_provider(provider_type)
        
        return {
            provider_type.value: provider_type in cls._providers
            for provider_type in SMSProviderType
        }
    
    @classmethod
    async def create_from_config(
        cls,
        config_dict: Dict[str, Any],
    ) -> SMSProviderInterface:
        """Create a provider from a configuration dictionary.
        
        Args:
            config_dict: Configuration dictionary with provider settings
            
        Returns:
            SMSProviderInterface instance
        """
        provider_type_str = config_dict.get("provider_type", "twilio")
        
        try:
            provider_type = SMSProviderType(provider_type_str)
        except ValueError:
            logger.warning(f"Unknown provider type '{provider_type_str}', using default")
            provider_type = cls._default_provider
        
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
        from .twilio_provider import TwilioSMSProvider
        SMSProviderFactory._providers[SMSProviderType.TWILIO] = TwilioSMSProvider
    except ImportError:
        pass
    
    try:
        from .africastalking_provider import AfricasTalkingSMSProvider
        SMSProviderFactory._providers[SMSProviderType.AFRICASTALKING] = AfricasTalkingSMSProvider
    except ImportError:
        pass


# Register providers on module load
_register_providers()
