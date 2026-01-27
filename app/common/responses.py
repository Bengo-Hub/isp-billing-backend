"""Standard API response utilities.

This module provides consistent response formats for all API endpoints.
"""

from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response format.

    Attributes:
        success: Always True for successful responses.
        data: The response payload.
        message: Optional success message.
    """

    success: bool = True
    data: T
    message: Optional[str] = None


class ListResponse(BaseModel, Generic[T]):
    """Response format for list operations without pagination.

    Attributes:
        success: Always True for successful responses.
        data: List of items.
        count: Total number of items in the response.
    """

    success: bool = True
    data: List[T]
    count: int


class MessageResponse(BaseModel):
    """Simple message response.

    Attributes:
        success: Whether the operation was successful.
        message: Descriptive message.
    """

    success: bool = True
    message: str


class DeleteResponse(BaseModel):
    """Response for delete operations.

    Attributes:
        success: Whether deletion was successful.
        message: Confirmation message.
        deleted_id: ID of the deleted resource.
    """

    success: bool = True
    message: str = "Resource deleted successfully"
    deleted_id: Optional[str] = None


def success_response(
    data: Any,
    message: Optional[str] = None,
    status_code: int = status.HTTP_200_OK,
) -> JSONResponse:
    """Create a standardized success response.

    Args:
        data: Response payload.
        message: Optional success message.
        status_code: HTTP status code.

    Returns:
        JSONResponse with standardized format.
    """
    content: Dict[str, Any] = {
        "success": True,
        "data": data,
    }
    if message:
        content["message"] = message

    return JSONResponse(content=content, status_code=status_code)


def created_response(
    data: Any,
    message: Optional[str] = None,
) -> JSONResponse:
    """Create a standardized response for resource creation.

    Args:
        data: Created resource data.
        message: Optional success message.

    Returns:
        JSONResponse with 201 status code.
    """
    return success_response(
        data=data,
        message=message or "Resource created successfully",
        status_code=status.HTTP_201_CREATED,
    )


def deleted_response(
    resource_id: Optional[str] = None,
    message: Optional[str] = None,
) -> JSONResponse:
    """Create a standardized response for resource deletion.

    Args:
        resource_id: ID of deleted resource.
        message: Optional message.

    Returns:
        JSONResponse with deletion confirmation.
    """
    content: Dict[str, Any] = {
        "success": True,
        "message": message or "Resource deleted successfully",
    }
    if resource_id:
        content["deleted_id"] = resource_id

    return JSONResponse(content=content, status_code=status.HTTP_200_OK)


def no_content_response() -> JSONResponse:
    """Create a 204 No Content response.

    Returns:
        Empty JSONResponse with 204 status code.
    """
    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)


def message_response(
    message: str,
    success: bool = True,
    status_code: int = status.HTTP_200_OK,
) -> JSONResponse:
    """Create a simple message response.

    Args:
        message: Response message.
        success: Whether operation was successful.
        status_code: HTTP status code.

    Returns:
        JSONResponse with message.
    """
    return JSONResponse(
        content={"success": success, "message": message},
        status_code=status_code,
    )
