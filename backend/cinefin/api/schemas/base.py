from typing import Any

from ninja import Field, Schema


class BaseResponseSchema(Schema):
    success: bool = Field(description="Indicates if the request was successful")
    message: str | None = Field(default=None, description="Human-readable message about the operation")


class ErrorResponseSchema(BaseResponseSchema):
    success: bool = Field(default=False, description="Always False for errors")
    error: str = Field(description="Error message describing what went wrong")
    error_code: str | None = Field(default=None, description="Machine-readable error code for client-side handling")
    details: dict[str, Any] | None = Field(
        default=None, description="Additional error details, such as field-specific validation errors"
    )


class SuccessResponseSchema(BaseResponseSchema):
    success: bool = Field(default=True, description="Always True for successful responses")
    data: dict[str, Any] | None = Field(default=None, description="Response data payload")


class MessageResponseSchema(BaseResponseSchema):
    success: bool = Field(default=True, description="Operation success status")
    message: str = Field(description="Success message")
