"""System health readout — under /api/v2/ (auth-gated), not /system/, since it exposes disk figures."""

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError
from cinefin.api.schemas.base import ErrorResponseSchema, SuccessResponseSchema
from cinefin.api.services import health_service

system_api = Router()


class HealthActionSchema(Schema):
    label: str = Field(..., description="Link text, e.g. 'Open security settings'")
    href: str = Field(..., description="Where the fix lives (app-relative URL)")


class HealthCheckSchema(Schema):
    key: str
    label: str
    status: str = Field(..., description='One of "ok", "warn", "error", "info"')
    detail: str
    hint: str | None = Field(None, description="Actionable next step when not OK")
    action: HealthActionSchema | None = Field(None, description="Link to where the fix lives, when one exists")


class HealthReportSchema(Schema):
    overall: str = Field(..., description='Worst status among checks: "ok", "warn" or "error"')
    version: str
    checked_at: str
    checks: list[HealthCheckSchema]


class HealthResponseSchema(SuccessResponseSchema):
    data: HealthReportSchema


class HealthCheckResponseSchema(SuccessResponseSchema):
    data: HealthCheckSchema


@system_api.get("/health", response={200: HealthResponseSchema, 500: ErrorResponseSchema})
def get_health(request: HttpRequest):
    return Status(
        200,
        HealthResponseSchema(
            message="System health retrieved",
            data=HealthReportSchema(**health_service.collect_health()),
        ),
    )


@system_api.post("/health/{key}", response={200: HealthCheckResponseSchema, 404: ErrorResponseSchema})
def recheck_health(request: HttpRequest, key: str):
    """Re-run one check by key (the topbar health menu's "Check again")."""
    result = health_service.run_check(key)
    if result is None:
        raise NotFoundError(f"Unknown health check: {key}", error_code="HEALTH_CHECK_NOT_FOUND")
    return Status(200, HealthCheckResponseSchema(message="Check re-run", data=HealthCheckSchema(**result)))
