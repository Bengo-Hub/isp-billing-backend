"""Custom exceptions for the ISP Billing System."""

from typing import Any, Dict, Optional


class ISPBaseException(Exception):
    """Base exception for ISP Billing System."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(ISPBaseException):
    """Raised when input validation fails."""
    pass


class RouterConnectionError(ISPBaseException):
    """Raised when router connection fails."""
    pass


class RouterOperationError(ISPBaseException):
    """Raised when router operation fails."""
    pass


class BillingError(ISPBaseException):
    """Raised when billing operation fails."""
    pass


class PaymentError(ISPBaseException):
    """Raised when payment operation fails."""
    pass


class SubscriptionError(ISPBaseException):
    """Raised when subscription operation fails."""
    pass


class NotificationError(ISPBaseException):
    """Raised when notification operation fails."""
    pass


class DatabaseError(ISPBaseException):
    """Raised when database operation fails."""
    pass


class AuthenticationError(ISPBaseException):
    """Raised when authentication fails."""
    pass


class AuthorizationError(ISPBaseException):
    """Raised when authorization fails."""
    pass


class ConfigurationError(ISPBaseException):
    """Raised when configuration is invalid."""
    pass


class ExternalServiceError(ISPBaseException):
    """Raised when external service operation fails."""
    pass


class ProvisioningError(ISPBaseException):
    """Raised when provisioning operation fails."""
    pass