from typing import Any

from ninja import Field, Schema


class BaseResponseSchema(Schema):
    success: bool
    message: str | None = None


class ErrorResponseSchema(BaseResponseSchema):
    success: bool = False
    error: str
    error_code: str | None = Field(default=None, description="Machine-readable error code")
    details: dict[str, Any] | None = None


class SuccessResponseSchema(BaseResponseSchema):
    success: bool = True
    data: dict[str, Any] | None = None


class MessageResponseSchema(BaseResponseSchema):
    success: bool = True
    message: str
