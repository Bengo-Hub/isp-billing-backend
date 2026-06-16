"""Standardized error codes and API exceptions.

This module provides a consistent error handling framework with:
- Enumerated error codes for all error types
- Structured API error responses
- HTTP status code mapping
- Error categorization by domain
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Standardized error codes organized by category.

    Code Format: CATEGORY_XXXX
    - AUTH (1xxx): Authentication and authorization errors
    - VAL (2xxx): Validation errors
    - RES (3xxx): Resource errors (not found, conflicts)
    - EXT (4xxx): External service errors
    - SYS (5xxx): System and infrastructure errors
    - BIZ (6xxx): Business logic errors
    """

    # Authentication & Authorization (1xxx)
    AUTH_INVALID_CREDENTIALS = "AUTH_1001"
    AUTH_TOKEN_EXPIRED = "AUTH_1002"
    AUTH_TOKEN_INVALID = "AUTH_1003"
    AUTH_INSUFFICIENT_PERMISSIONS = "AUTH_1004"
    AUTH_ACCOUNT_DISABLED = "AUTH_1005"
    AUTH_ACCOUNT_NOT_VERIFIED = "AUTH_1006"
    AUTH_SESSION_EXPIRED = "AUTH_1007"
    AUTH_REFRESH_TOKEN_INVALID = "AUTH_1008"
    AUTH_MFA_REQUIRED = "AUTH_1009"
    AUTH_MFA_INVALID = "AUTH_1010"
    AUTH_PASSWORD_WEAK = "AUTH_1011"
    AUTH_PASSWORD_EXPIRED = "AUTH_1012"
    AUTH_ROLE_NOT_FOUND = "AUTH_1013"
    AUTH_PERMISSION_DENIED = "AUTH_1014"

    # Validation (2xxx)
    VAL_REQUIRED_FIELD = "VAL_2001"
    VAL_INVALID_FORMAT = "VAL_2002"
    VAL_FIELD_TOO_LONG = "VAL_2003"
    VAL_FIELD_TOO_SHORT = "VAL_2004"
    VAL_INVALID_EMAIL = "VAL_2005"
    VAL_INVALID_PHONE = "VAL_2006"
    VAL_INVALID_DATE = "VAL_2007"
    VAL_INVALID_ENUM = "VAL_2008"
    VAL_INVALID_RANGE = "VAL_2009"
    VAL_DUPLICATE_VALUE = "VAL_2010"
    VAL_INVALID_JSON = "VAL_2011"
    VAL_FILE_TOO_LARGE = "VAL_2012"
    VAL_INVALID_FILE_TYPE = "VAL_2013"

    # Resource (3xxx)
    RES_NOT_FOUND = "RES_3001"
    RES_ALREADY_EXISTS = "RES_3002"
    RES_CONFLICT = "RES_3003"
    RES_DELETED = "RES_3004"
    RES_LOCKED = "RES_3005"
    RES_DEPENDENCY_EXISTS = "RES_3006"

    # External Services (4xxx)
    EXT_MIKROTIK_CONNECTION_FAILED = "EXT_4001"
    EXT_MIKROTIK_AUTH_FAILED = "EXT_4002"
    EXT_MIKROTIK_COMMAND_FAILED = "EXT_4003"
    EXT_MIKROTIK_TIMEOUT = "EXT_4004"
    EXT_MPESA_REQUEST_FAILED = "EXT_4010"
    EXT_MPESA_TIMEOUT = "EXT_4011"
    EXT_MPESA_CALLBACK_FAILED = "EXT_4012"
    EXT_MPESA_INSUFFICIENT_FUNDS = "EXT_4013"
    EXT_SMS_DELIVERY_FAILED = "EXT_4020"
    EXT_SMS_INSUFFICIENT_CREDITS = "EXT_4021"
    EXT_SMS_PROVIDER_ERROR = "EXT_4022"
    EXT_EMAIL_DELIVERY_FAILED = "EXT_4030"
    EXT_EMAIL_INVALID_ADDRESS = "EXT_4031"
    EXT_SERVICE_UNAVAILABLE = "EXT_4099"

    # System (5xxx)
    SYS_INTERNAL_ERROR = "SYS_5001"
    SYS_DATABASE_ERROR = "SYS_5002"
    SYS_CACHE_ERROR = "SYS_5003"
    SYS_QUEUE_ERROR = "SYS_5004"
    SYS_RATE_LIMIT_EXCEEDED = "SYS_5005"
    SYS_MAINTENANCE_MODE = "SYS_5006"
    SYS_CONFIGURATION_ERROR = "SYS_5007"
    SYS_DISK_FULL = "SYS_5008"
    SYS_MEMORY_ERROR = "SYS_5009"
    SYS_CIRCUIT_OPEN = "SYS_5010"

    # Business Logic (6xxx)
    BIZ_SUBSCRIPTION_EXPIRED = "BIZ_6001"
    BIZ_SUBSCRIPTION_LIMIT_REACHED = "BIZ_6002"
    BIZ_PAYMENT_REQUIRED = "BIZ_6003"
    BIZ_LICENCE_EXPIRED = "BIZ_6004"
    BIZ_LICENCE_INVALID = "BIZ_6005"
    BIZ_LICENCE_LIMIT_REACHED = "BIZ_6006"
    BIZ_PROVISIONING_IN_PROGRESS = "BIZ_6010"
    BIZ_PROVISIONING_FAILED = "BIZ_6011"
    BIZ_ROUTER_OFFLINE = "BIZ_6012"
    BIZ_INSUFFICIENT_BALANCE = "BIZ_6020"
    BIZ_INVOICE_ALREADY_PAID = "BIZ_6021"
    BIZ_INVALID_OPERATION = "BIZ_6099"


# HTTP status code mapping for error codes
ERROR_HTTP_STATUS: Dict[ErrorCode, int] = {
    # Auth errors -> 401/403
    ErrorCode.AUTH_INVALID_CREDENTIALS: 401,
    ErrorCode.AUTH_TOKEN_EXPIRED: 401,
    ErrorCode.AUTH_TOKEN_INVALID: 401,
    ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS: 403,
    ErrorCode.AUTH_ACCOUNT_DISABLED: 403,
    ErrorCode.AUTH_ACCOUNT_NOT_VERIFIED: 403,
    ErrorCode.AUTH_SESSION_EXPIRED: 401,
    ErrorCode.AUTH_REFRESH_TOKEN_INVALID: 401,
    ErrorCode.AUTH_MFA_REQUIRED: 403,
    ErrorCode.AUTH_MFA_INVALID: 401,
    ErrorCode.AUTH_PASSWORD_WEAK: 400,
    ErrorCode.AUTH_PASSWORD_EXPIRED: 403,
    ErrorCode.AUTH_ROLE_NOT_FOUND: 404,
    ErrorCode.AUTH_PERMISSION_DENIED: 403,

    # Validation errors -> 400/422
    ErrorCode.VAL_REQUIRED_FIELD: 422,
    ErrorCode.VAL_INVALID_FORMAT: 422,
    ErrorCode.VAL_FIELD_TOO_LONG: 422,
    ErrorCode.VAL_FIELD_TOO_SHORT: 422,
    ErrorCode.VAL_INVALID_EMAIL: 422,
    ErrorCode.VAL_INVALID_PHONE: 422,
    ErrorCode.VAL_INVALID_DATE: 422,
    ErrorCode.VAL_INVALID_ENUM: 422,
    ErrorCode.VAL_INVALID_RANGE: 422,
    ErrorCode.VAL_DUPLICATE_VALUE: 409,
    ErrorCode.VAL_INVALID_JSON: 400,
    ErrorCode.VAL_FILE_TOO_LARGE: 413,
    ErrorCode.VAL_INVALID_FILE_TYPE: 415,

    # Resource errors -> 404/409
    ErrorCode.RES_NOT_FOUND: 404,
    ErrorCode.RES_ALREADY_EXISTS: 409,
    ErrorCode.RES_CONFLICT: 409,
    ErrorCode.RES_DELETED: 410,
    ErrorCode.RES_LOCKED: 423,
    ErrorCode.RES_DEPENDENCY_EXISTS: 409,

    # External service errors -> 502/503/504
    ErrorCode.EXT_MIKROTIK_CONNECTION_FAILED: 502,
    ErrorCode.EXT_MIKROTIK_AUTH_FAILED: 502,
    ErrorCode.EXT_MIKROTIK_COMMAND_FAILED: 502,
    ErrorCode.EXT_MIKROTIK_TIMEOUT: 504,
    ErrorCode.EXT_MPESA_REQUEST_FAILED: 502,
    ErrorCode.EXT_MPESA_TIMEOUT: 504,
    ErrorCode.EXT_MPESA_CALLBACK_FAILED: 502,
    ErrorCode.EXT_MPESA_INSUFFICIENT_FUNDS: 402,
    ErrorCode.EXT_SMS_DELIVERY_FAILED: 502,
    ErrorCode.EXT_SMS_INSUFFICIENT_CREDITS: 402,
    ErrorCode.EXT_SMS_PROVIDER_ERROR: 502,
    ErrorCode.EXT_EMAIL_DELIVERY_FAILED: 502,
    ErrorCode.EXT_EMAIL_INVALID_ADDRESS: 400,
    ErrorCode.EXT_SERVICE_UNAVAILABLE: 503,

    # System errors -> 500/503/429
    ErrorCode.SYS_INTERNAL_ERROR: 500,
    ErrorCode.SYS_DATABASE_ERROR: 500,
    ErrorCode.SYS_CACHE_ERROR: 500,
    ErrorCode.SYS_QUEUE_ERROR: 500,
    ErrorCode.SYS_RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.SYS_MAINTENANCE_MODE: 503,
    ErrorCode.SYS_CONFIGURATION_ERROR: 500,
    ErrorCode.SYS_DISK_FULL: 507,
    ErrorCode.SYS_MEMORY_ERROR: 500,
    ErrorCode.SYS_CIRCUIT_OPEN: 503,

    # Business logic errors -> 400/402/409
    ErrorCode.BIZ_SUBSCRIPTION_EXPIRED: 402,
    ErrorCode.BIZ_SUBSCRIPTION_LIMIT_REACHED: 402,
    ErrorCode.BIZ_PAYMENT_REQUIRED: 402,
    ErrorCode.BIZ_LICENCE_EXPIRED: 402,
    ErrorCode.BIZ_LICENCE_INVALID: 400,
    ErrorCode.BIZ_LICENCE_LIMIT_REACHED: 402,
    ErrorCode.BIZ_PROVISIONING_IN_PROGRESS: 409,
    ErrorCode.BIZ_PROVISIONING_FAILED: 500,
    ErrorCode.BIZ_ROUTER_OFFLINE: 503,
    ErrorCode.BIZ_INSUFFICIENT_BALANCE: 402,
    ErrorCode.BIZ_INVOICE_ALREADY_PAID: 409,
    ErrorCode.BIZ_INVALID_OPERATION: 400,
}


class FieldError(BaseModel):
    """Individual field validation error."""

    field: str
    message: str
    code: Optional[str] = None


class ErrorDetail(BaseModel):
    """Structured error detail for API responses."""

    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    field_errors: Optional[List[FieldError]] = None
    trace_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard API error response format."""

    success: bool = False
    error: ErrorDetail


class APIError(Exception):
    """Base exception for API errors with standardized error codes.

    This exception should be raised in services and will be caught by
    the global exception handler to return a standardized JSON response.

    Attributes:
        code: The ErrorCode enum value identifying this error type.
        message: Human-readable error message.
        details: Optional dictionary with additional context.
        field_errors: Optional list of field-specific validation errors.
        http_status: HTTP status code (auto-derived from code if not set).
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        field_errors: Optional[List[FieldError]] = None,
        http_status: Optional[int] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.field_errors = field_errors
        self.http_status = http_status or ERROR_HTTP_STATUS.get(code, 400)
        super().__init__(self.message)

    def to_response(self, trace_id: Optional[str] = None) -> ErrorResponse:
        """Convert exception to ErrorResponse model.

        Args:
            trace_id: Optional request trace ID for debugging.

        Returns:
            Structured ErrorResponse for JSON serialization.
        """
        return ErrorResponse(
            success=False,
            error=ErrorDetail(
                code=self.code.value,
                message=self.message,
                details=self.details if self.details else None,
                field_errors=self.field_errors,
                trace_id=trace_id,
            ),
        )


# Convenience exception classes for common error types
class AuthenticationError(APIError):
    """Authentication failure."""

    def __init__(
        self,
        message: str = "Authentication failed",
        code: ErrorCode = ErrorCode.AUTH_INVALID_CREDENTIALS,
        **kwargs: Any,
    ):
        super().__init__(code=code, message=message, **kwargs)


class AuthorizationError(APIError):
    """Authorization/permission failure."""

    def __init__(
        self,
        message: str = "Permission denied",
        code: ErrorCode = ErrorCode.AUTH_PERMISSION_DENIED,
        **kwargs: Any,
    ):
        super().__init__(code=code, message=message, **kwargs)


class ValidationError(APIError):
    """Input validation failure."""

    def __init__(
        self,
        message: str = "Validation failed",
        code: ErrorCode = ErrorCode.VAL_INVALID_FORMAT,
        field_errors: Optional[List[FieldError]] = None,
        **kwargs: Any,
    ):
        super().__init__(code=code, message=message, field_errors=field_errors, **kwargs)


class NotFoundError(APIError):
    """Resource not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {}
        if resource_type:
            details["resource_type"] = resource_type
        if resource_id:
            details["resource_id"] = resource_id

        super().__init__(
            code=ErrorCode.RES_NOT_FOUND,
            message=message,
            details=details if details else None,
            **kwargs,
        )


class ConflictError(APIError):
    """Resource conflict (already exists, locked, etc.)."""

    def __init__(
        self,
        message: str = "Resource conflict",
        code: ErrorCode = ErrorCode.RES_CONFLICT,
        **kwargs: Any,
    ):
        super().__init__(code=code, message=message, **kwargs)


class ExternalServiceError(APIError):
    """External service failure."""

    def __init__(
        self,
        message: str = "External service error",
        code: ErrorCode = ErrorCode.EXT_SERVICE_UNAVAILABLE,
        service_name: Optional[str] = None,
        **kwargs: Any,
    ):
        details = kwargs.pop("details", {}) or {}
        if service_name:
            details["service"] = service_name

        super().__init__(code=code, message=message, details=details, **kwargs)


class RateLimitError(APIError):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        **kwargs: Any,
    ):
        details = {}
        if retry_after:
            details["retry_after_seconds"] = retry_after

        super().__init__(
            code=ErrorCode.SYS_RATE_LIMIT_EXCEEDED,
            message=message,
            details=details if details else None,
            **kwargs,
        )


class BusinessError(APIError):
    """Business logic error."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.BIZ_INVALID_OPERATION,
        **kwargs: Any,
    ):
        super().__init__(code=code, message=message, **kwargs)


# Exception handler for FastAPI
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Global exception handler for APIError.

    This handler converts APIError exceptions into standardized JSON responses.
    It should be registered with FastAPI using app.add_exception_handler().

    Args:
        request: The incoming FastAPI request.
        exc: The APIError exception that was raised.

    Returns:
        JSONResponse with standardized error format.
    """
    # Get trace ID from request state if available
    trace_id = getattr(request.state, "trace_id", None)

    response = exc.to_response(trace_id=trace_id)

    return JSONResponse(
        status_code=exc.http_status,
        content=response.model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handler for standard HTTPException to standardize response format.

    Args:
        request: The incoming FastAPI request.
        exc: The HTTPException that was raised.

    Returns:
        JSONResponse with standardized error format.
    """
    trace_id = getattr(request.state, "trace_id", None)

    # Map HTTP status to error code
    status_to_code = {
        400: ErrorCode.VAL_INVALID_FORMAT,
        401: ErrorCode.AUTH_TOKEN_INVALID,
        403: ErrorCode.AUTH_PERMISSION_DENIED,
        404: ErrorCode.RES_NOT_FOUND,
        405: ErrorCode.BIZ_INVALID_OPERATION,
        409: ErrorCode.RES_CONFLICT,
        422: ErrorCode.VAL_INVALID_FORMAT,
        429: ErrorCode.SYS_RATE_LIMIT_EXCEEDED,
        500: ErrorCode.SYS_INTERNAL_ERROR,
        502: ErrorCode.EXT_SERVICE_UNAVAILABLE,
        503: ErrorCode.SYS_MAINTENANCE_MODE,
    }

    code = status_to_code.get(exc.status_code, ErrorCode.SYS_INTERNAL_ERROR)

    # Preserve STRUCTURED dict details instead of stringifying them. Endpoints may
    # raise HTTPException(detail={"code": "subscription_inactive", "upgrade": True,
    # "message": ..., "contact": {...}}); the frontend discriminates the 403 on
    # error.code (e.g. subscription_inactive / provider_subscription_inactive) and
    # reads payload fields (e.g. the captive provider contact card) from
    # error.details. str(exc.detail) used to flatten all that into one message.
    detail = exc.detail
    if isinstance(detail, dict):
        error = ErrorDetail(
            code=str(detail.get("code") or code.value),
            message=str(detail.get("message") or detail.get("error") or "Request failed"),
            details={k: v for k, v in detail.items() if k not in ("code", "message")} or None,
            trace_id=trace_id,
        )
    else:
        error = ErrorDetail(
            code=code.value,
            message=str(detail),
            trace_id=trace_id,
        )

    response = ErrorResponse(success=False, error=error)

    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(exclude_none=True),
    )


def register_exception_handlers(app: Any) -> None:
    """Register all custom exception handlers with the FastAPI app.

    Args:
        app: FastAPI application instance.
    """
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
