"""
Payment gateway factory for instantiating gateway implementations.

Provides a centralized way to create payment gateway instances
based on gateway type and configuration.
"""

import json
import logging
from typing import Dict, Any, Optional, Type

from cryptography.fernet import Fernet

from app.core.config import settings
from app.models.payment_gateway import GatewayType, PaymentGatewayConfig
from .base import PaymentGatewayInterface

logger = logging.getLogger(__name__)


class PaymentGatewayFactory:
    """
    Factory for creating payment gateway instances.

    Supports all configured gateway types and handles credential decryption.
    """

    # Registry of gateway implementations
    _gateway_registry: Dict[GatewayType, Type[PaymentGatewayInterface]] = {}

    @classmethod
    def register(cls, gateway_type: GatewayType):
        """
        Decorator to register a gateway implementation.

        Usage:
            @PaymentGatewayFactory.register(GatewayType.MPESA_PAYBILL)
            class MPesaPaybillGateway(PaymentGatewayInterface):
                ...
        """
        def decorator(gateway_class: Type[PaymentGatewayInterface]):
            cls._gateway_registry[gateway_type] = gateway_class
            return gateway_class
        return decorator

    @classmethod
    def create(
        cls,
        gateway_config: PaymentGatewayConfig,
        encryption_key: Optional[str] = None,
    ) -> PaymentGatewayInterface:
        """
        Create a payment gateway instance from configuration.

        Args:
            gateway_config: PaymentGatewayConfig model instance
            encryption_key: Key for decrypting credentials (uses settings if not provided)

        Returns:
            Configured PaymentGatewayInterface implementation

        Raises:
            ValueError: If gateway type is not supported
            RuntimeError: If gateway creation fails
        """
        gateway_type = gateway_config.gateway_type

        if gateway_type not in cls._gateway_registry:
            raise ValueError(f"Unsupported gateway type: {gateway_type}")

        gateway_class = cls._gateway_registry[gateway_type]

        # Prepare configuration
        config = cls._prepare_config(gateway_config, encryption_key)

        try:
            return gateway_class(config)
        except Exception as e:
            logger.error(f"Failed to create gateway {gateway_type}: {e}")
            raise RuntimeError(f"Failed to create payment gateway: {e}")

    @classmethod
    def create_from_type(
        cls,
        gateway_type: GatewayType,
        credentials: Dict[str, Any],
        **kwargs,
    ) -> PaymentGatewayInterface:
        """
        Create a payment gateway instance directly from type and credentials.

        Useful for testing or when gateway config is not from database.

        Args:
            gateway_type: Type of gateway to create
            credentials: Gateway credentials
            **kwargs: Additional configuration options

        Returns:
            Configured PaymentGatewayInterface implementation
        """
        if gateway_type not in cls._gateway_registry:
            raise ValueError(f"Unsupported gateway type: {gateway_type}")

        gateway_class = cls._gateway_registry[gateway_type]

        config = {
            "credentials": credentials,
            **kwargs,
        }

        return gateway_class(config)

    @classmethod
    def _prepare_config(
        cls,
        gateway_config: PaymentGatewayConfig,
        encryption_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Prepare gateway configuration from database model.

        Decrypts credentials and merges all configuration fields.
        """
        # Decrypt credentials if present
        credentials = {}
        if gateway_config.credentials:
            key = encryption_key or getattr(settings, "encryption_key", None)
            if key:
                try:
                    credentials = cls._decrypt_credentials(
                        gateway_config.credentials, key
                    )
                except Exception as e:
                    logger.error(f"Failed to decrypt gateway credentials: {e}")
                    credentials = {}
            else:
                # Try parsing as plain JSON (for development)
                try:
                    credentials = json.loads(gateway_config.credentials)
                except json.JSONDecodeError:
                    credentials = {}

        return {
            "gateway_id": gateway_config.id,
            "organization_id": gateway_config.organization_id,
            "gateway_type": gateway_config.gateway_type,
            "name": gateway_config.name,
            "is_active": gateway_config.is_active,
            "is_primary": gateway_config.is_primary,
            "credentials": credentials,
            "callback_url": gateway_config.callback_url,
            "callback_secret": gateway_config.callback_secret,
            "paybill_number": gateway_config.paybill_number,
            "till_number": gateway_config.till_number,
            "account_number_format": gateway_config.account_number_format,
            "bank_name": gateway_config.bank_name,
            "bank_account_number": gateway_config.bank_account_number,
            "bank_account_name": gateway_config.bank_account_name,
            "min_amount": float(gateway_config.min_amount) if gateway_config.min_amount else 10,
            "max_amount": float(gateway_config.max_amount) if gateway_config.max_amount else 150000,
            "requires_manual_reconciliation": gateway_config.requires_manual_reconciliation,
        }

    @classmethod
    def _decrypt_credentials(cls, encrypted: str, key: str) -> Dict[str, Any]:
        """
        Decrypt gateway credentials.

        Args:
            encrypted: Encrypted credentials string
            key: Fernet encryption key

        Returns:
            Decrypted credentials dictionary
        """
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        decrypted = fernet.decrypt(encrypted.encode() if isinstance(encrypted, str) else encrypted)
        return json.loads(decrypted.decode())

    @classmethod
    def encrypt_credentials(cls, credentials: Dict[str, Any], key: Optional[str] = None) -> str:
        """
        Encrypt gateway credentials for storage.

        Args:
            credentials: Credentials dictionary
            key: Fernet encryption key (uses settings if not provided)

        Returns:
            Encrypted credentials string
        """
        encryption_key = key or getattr(settings, "encryption_key", None)
        if not encryption_key:
            # Return as plain JSON for development
            return json.dumps(credentials)

        fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        encrypted = fernet.encrypt(json.dumps(credentials).encode())
        return encrypted.decode()

    @classmethod
    def get_supported_gateways(cls) -> list:
        """
        Get list of supported gateway types.

        Returns:
            List of GatewayType values that have registered implementations
        """
        return list(cls._gateway_registry.keys())

    @classmethod
    def is_supported(cls, gateway_type: GatewayType) -> bool:
        """
        Check if a gateway type is supported.

        Args:
            gateway_type: Gateway type to check

        Returns:
            True if gateway type has a registered implementation
        """
        return gateway_type in cls._gateway_registry

    @classmethod
    def get_gateway_info(cls, gateway_type: GatewayType) -> Dict[str, Any]:
        """
        Get information about a gateway type.

        Args:
            gateway_type: Gateway type

        Returns:
            Dictionary with gateway information
        """
        gateway_info = {
            GatewayType.MPESA_PAYBILL: {
                "name": "M-PESA Paybill",
                "description": "Lipa na M-PESA Paybill with Daraja API",
                "requires_api": True,
                "supports_stk_push": True,
                "supports_c2b": True,
                "supports_b2c": True,
                "supports_refunds": True,
                "required_fields": ["consumer_key", "consumer_secret", "passkey", "shortcode"],
            },
            GatewayType.MPESA_TILL: {
                "name": "M-PESA Till/Buy Goods",
                "description": "Lipa na M-PESA Till Number with Daraja API",
                "requires_api": True,
                "supports_stk_push": True,
                "supports_c2b": True,
                "supports_b2c": False,
                "supports_refunds": False,
                "required_fields": ["consumer_key", "consumer_secret", "passkey", "till_number"],
            },
            GatewayType.MPESA_PAYBILL_NO_API: {
                "name": "M-PESA Paybill (Manual)",
                "description": "M-PESA Paybill without API - requires manual reconciliation",
                "requires_api": False,
                "supports_stk_push": False,
                "supports_c2b": False,
                "supports_b2c": False,
                "supports_refunds": False,
                "required_fields": ["paybill_number"],
            },
            GatewayType.MPESA_TILL_NO_API: {
                "name": "M-PESA Till (Manual)",
                "description": "M-PESA Till without API - requires manual reconciliation",
                "requires_api": False,
                "supports_stk_push": False,
                "supports_c2b": False,
                "supports_b2c": False,
                "supports_refunds": False,
                "required_fields": ["till_number"],
            },
            GatewayType.BANK_ACCOUNT: {
                "name": "Bank Account",
                "description": "Direct bank transfer via Paybill",
                "requires_api": False,
                "supports_stk_push": False,
                "supports_c2b": False,
                "supports_b2c": False,
                "supports_refunds": False,
                "required_fields": ["bank_name", "bank_account_number", "paybill_number"],
            },
            GatewayType.PAYSTACK: {
                "name": "Paystack",
                "description": "Card and mobile money payments via Paystack",
                "requires_api": True,
                "supports_stk_push": False,
                "supports_c2b": True,
                "supports_b2c": True,
                "supports_refunds": True,
                "required_fields": ["secret_key", "public_key"],
            },
            GatewayType.PAYPAL: {
                "name": "PayPal",
                "description": "PayPal payments for international customers",
                "requires_api": True,
                "supports_stk_push": False,
                "supports_c2b": True,
                "supports_b2c": True,
                "supports_refunds": True,
                "required_fields": ["client_id", "client_secret"],
            },
            GatewayType.PESAPAL: {
                "name": "PesaPal",
                "description": "Multi-channel payments via PesaPal",
                "requires_api": True,
                "supports_stk_push": True,
                "supports_c2b": True,
                "supports_b2c": False,
                "supports_refunds": False,
                "required_fields": ["consumer_key", "consumer_secret"],
            },
            GatewayType.KOPOKOPO: {
                "name": "Kopo Kopo",
                "description": "M-PESA integration via Kopo Kopo",
                "requires_api": True,
                "supports_stk_push": True,
                "supports_c2b": True,
                "supports_b2c": True,
                "supports_refunds": False,
                "required_fields": ["client_id", "client_secret", "api_key"],
            },
        }

        return gateway_info.get(gateway_type, {
            "name": gateway_type.value,
            "description": "Unknown gateway type",
            "requires_api": False,
            "supports_stk_push": False,
            "supports_c2b": False,
            "supports_b2c": False,
            "supports_refunds": False,
            "required_fields": [],
        })
