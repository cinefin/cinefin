"""Custom exception classes for API error handling."""

from typing import Any


class APIException(Exception):
    """Base API exception: HTTP status code + machine-readable error code."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(
        self, message: str | None = None, error_code: str | None = None, details: dict[str, Any] | None = None
    ):
        self.message = message or self.message
        self.error_code = error_code or self.error_code
        self.details = details
        super().__init__(self.message)


class ValidationError(APIException):
    status_code = 400
    error_code = "VALIDATION_ERROR"
    message = "Invalid request data"


class BadRequestError(APIException):
    status_code = 400
    error_code = "BAD_REQUEST"
    message = "Bad request"


class AuthenticationError(APIException):
    status_code = 401
    error_code = "AUTHENTICATION_FAILED"
    message = "Authentication required"


class PermissionError(APIException):
    status_code = 403
    error_code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action"


class NotFoundError(APIException):
    status_code = 404
    error_code = "NOT_FOUND"
    message = "Resource not found"


class ConflictError(APIException):
    status_code = 409
    error_code = "CONFLICT"
    message = "Request conflicts with current state"


class UnprocessableEntityError(APIException):
    status_code = 422
    error_code = "UNPROCESSABLE_ENTITY"
    message = "Unable to process request"


class InternalServerError(APIException):
    status_code = 500
    error_code = "INTERNAL_ERROR"
    message = "Internal server error"
