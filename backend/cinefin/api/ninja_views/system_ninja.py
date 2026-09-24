"""System health readout — under /api/v2/ (auth-gated), not /system/, since it exposes disk figures."""

import logging

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError
from cinefin.api.schemas.base import ErrorResponseSchema, SuccessResponseSchema
from cinefin.api.services import health_service

logger = logging.getLogger(__name__)

system_api = Router()


class HealthActionSchema(Schema):
    label: str = Field(..., description="Link text, e.g. 'Open security settings'")
    href: str = Field(..., description="Where the fix lives (app-relative URL)")


class HealthCheckSchema(Schema):
    key: str = Field(..., description="Stable machine key for the check")
    label: str = Field(..., description="Human-readable check name")
    status: str = Field(..., description='One of "ok", "warn", "error", "info"')
    detail: str = Field(..., description="Human-readable result")
    hint: str | None = Field(None, description="Actionable next step when not OK")
    action: HealthActionSchema | None = Field(None, description="Link to where the fix lives, when one exists")


class HealthReportSchema(Schema):
    overall: str = Field(..., description='Worst status among checks: "ok", "warn" or "error"')
    version: str = Field(..., description="Running application version")
    checked_at: str = Field(..., description="When the report was generated (ISO)")
    checks: list[HealthCheckSchema] = Field(..., description="Per-check results")


class HealthResponseSchema(SuccessResponseSchema):
    data: HealthReportSchema = Field(..., description="The system health report")


class HealthCheckResponseSchema(SuccessResponseSchema):
    data: HealthCheckSchema = Field(..., description="The re-run check result")


@system_api.get("/health", response={200: HealthResponseSchema, 500: ErrorResponseSchema})
def get_health(request: HttpRequest):
    return Status(
        200,
        HealthResponseSchema(
            message="System health retrieved",
            data=HealthReportSchema(**health_service.collect_health()),
        ),
    )


@system_api.get("/health/checks/{key}", response={200: HealthCheckResponseSchema, 404: ErrorResponseSchema})
def rerun_health_check(request: HttpRequest, key: str):
    check = health_service.run_check(key)
    if check is None:
        raise NotFoundError(f"Unknown health check: {key}")
    return Status(
        200,
        HealthCheckResponseSchema(
            message="Health check re-run",
            data=HealthCheckSchema(**check),
        ),
    )
