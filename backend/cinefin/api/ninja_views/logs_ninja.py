"""Logs API — one-shot access to the in-memory application log ring buffer."""

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema

from cinefin.api.schemas.base import SuccessResponseSchema
from cinefin.log_buffer import buffer, level_number

logs_api = Router()

MAX_LIMIT = 2000


class LogRecordSchema(Schema):
    seq: int = Field(..., description="Monotonic record sequence number (per process)")
    ts: str = Field(..., description="Record timestamp (local ISO format)")
    level: str = Field(..., description="Log level name (DEBUG/INFO/WARNING/ERROR/CRITICAL)")
    logger: str = Field(..., description="Logger name that emitted the record")
    message: str = Field(..., description="Rendered log message (includes traceback if any)")


class LogsDataSchema(Schema):
    records: list[LogRecordSchema] = Field(..., description="Matching records, oldest first")
    count: int = Field(..., description="Number of records returned")


class LogsResponseSchema(SuccessResponseSchema):
    data: LogsDataSchema = Field(..., description="Log records data")


class LogsFilters(Schema):
    level: str = Field("INFO", description="Minimum level to include (DEBUG/INFO/WARNING/ERROR)")
    limit: int = Field(200, ge=1, le=MAX_LIMIT, description="Maximum number of records to return")


@logs_api.get("", response=LogsResponseSchema, summary="Recent application log records")
def list_logs(request: HttpRequest, filters: Query[LogsFilters]):
    records, _seq = buffer.snapshot(min_levelno=level_number(filters.level), limit=filters.limit)
    return {"success": True, "data": {"records": records, "count": len(records)}}
