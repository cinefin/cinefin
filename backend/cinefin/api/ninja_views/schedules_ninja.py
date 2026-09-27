import logging
from datetime import datetime

import pytz
from django.http import HttpRequest
from django.utils import timezone
from ninja import Field, Query, Router, Schema, Status

from cinefin.api.exceptions import ConflictError, NotFoundError, ValidationError
from cinefin.api.models import Programme, ProgrammeSchedule
from cinefin.api.models.automation import default_lead_in
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema

logger = logging.getLogger(__name__)


class ProgrammeBasicSchema(Schema):
    id: int = Field(..., description="Programme ID")
    name: str = Field(..., description="Programme name")
    runtime: int = Field(..., description="Programme runtime in minutes")
    formatted_runtime: str | None = Field(None, description="Human-readable formatted runtime")
    description: str | None = Field(None, description="Programme description")


class ScheduleSchema(Schema):
    id: int = Field(..., description="Schedule ID")
    programme: ProgrammeBasicSchema = Field(..., description="Associated programme details")
    start_time: str = Field(..., description="When the lead-in begins (ISO)")
    play_time: str = Field(..., description="When the programme plays: start_time + lead-in (ISO)")
    lead_in: int | None = Field(None, description="Lead-in override in seconds (null = the default)")
    runtime: int = Field(..., description="Programme runtime in minutes")
    status: str = Field(..., description="Schedule status (scheduled, running, completed, cancelled, failed, missed)")
    last_error: str | None = Field(None, description="Reason the run failed, if any")
    created_at: str = Field(..., description="Schedule creation timestamp in ISO format")
    end_time: str | None = Field(None, description="When the screening ends: play_time + runtime (ISO)")


class ScheduleListFilters(Schema):
    status: str | None = Field(None, description="Filter by schedule status")
    programme_id: int | None = Field(None, description="Filter by programme ID")
    date_from: str | None = Field(None, description="Filter schedules from this date (ISO format)")
    date_to: str | None = Field(None, description="Filter schedules to this date (ISO format)")
    show_past: bool = Field(False, description="Include past schedules in results")


class ScheduleListDataSchema(Schema):
    schedules: list[ScheduleSchema] = Field(..., description="List of scheduled programmes")
    count: int = Field(..., description="Total number of schedules returned")
    default_lead_in: int = Field(0, description="The global lead-in in seconds (scheduler.lead_in)")


class ScheduleListResponseSchema(SuccessResponseSchema):
    data: ScheduleListDataSchema = Field(..., description="Schedule list data")


class CreateScheduleSchema(Schema):
    programme_id: int = Field(..., description="ID of programme to schedule")
    start_time: str = Field(..., description="When the lead-in begins, in ISO format")
    timezone: str = Field("UTC", description="Timezone for the start time")
    lead_in: int | None = Field(None, ge=0, description="Lead-in override in seconds (null = the default)")


class UpdateScheduleSchema(Schema):
    start_time: str = Field(..., description="When the lead-in begins, in ISO format")
    timezone: str = Field("UTC", description="Timezone for the start time")
    lead_in: int | None = Field(None, ge=0, description="Lead-in override in seconds (null = the default)")


class ScheduleDataSchema(Schema):
    schedule: ScheduleSchema = Field(..., description="Schedule details")


class ScheduleCreateResponseSchema(SuccessResponseSchema):
    data: ScheduleDataSchema = Field(..., description="Created schedule data")


class RunnerStatusSchema(Schema):
    running: bool = Field(..., description="Whether the schedule runner appears to be alive")
    pid: int | None = Field(None, description="Process id hosting the runner thread")
    last_beat: str | None = Field(None, description="Last heartbeat (ISO)")
    age_seconds: float | None = Field(None, description="Seconds since last heartbeat")
    tick_seconds: int | None = Field(None, description="Runner poll interval")


class RunnerStatusResponseSchema(SuccessResponseSchema):
    data: RunnerStatusSchema = Field(..., description="Runner status")


schedules_api = Router()


def _reject_overlap(schedule: ProgrammeSchedule) -> None:
    """A screening occupies start_time (lead-in) → end_time; two active ones may not overlap."""
    default = default_lead_in()
    start, end = schedule.start_time, schedule.end_time(default)
    others = ProgrammeSchedule.objects.filter(status__in=["scheduled", "running"], start_time__lt=end).exclude(
        id=schedule.id
    )
    clash = next((o for o in others.select_related("programme") if o.end_time(default) > start), None)
    if clash:
        raise ConflictError(
            f"Overlaps “{clash.programme.name}” "
            f"({timezone.localtime(clash.start_time):%H:%M}–{timezone.localtime(clash.end_time(default)):%H:%M})",
            error_code="SCHEDULE_OVERLAP",
            details={"schedule_id": clash.id},
        )


# Schedule status is owned by the in-process schedule runner
# (services/schedule_runner.py); the API only reads/writes rows.


@schedules_api.get("/runner", response={200: RunnerStatusResponseSchema, 500: ErrorResponseSchema})
def get_runner_status(request: HttpRequest):
    from cinefin.api.services import schedule_runner

    return Status(
        200,
        RunnerStatusResponseSchema(
            message="Runner status retrieved", data=RunnerStatusSchema(**schedule_runner.runner_status())
        ),
    )


def serialize_programme_basic(programme: Programme) -> ProgrammeBasicSchema:
    return ProgrammeBasicSchema(
        id=programme.id,
        name=programme.name,
        runtime=programme.get_runtime(),
        formatted_runtime=programme.get_formatted_runtime(),
        description=programme.description,
    )


def serialize_schedule(schedule: ProgrammeSchedule, default_lead_in: int | None = None) -> ScheduleSchema:
    return ScheduleSchema(
        id=schedule.id,
        programme=serialize_programme_basic(schedule.programme),
        start_time=schedule.start_time.isoformat(),
        play_time=schedule.play_time(default_lead_in).isoformat(),
        lead_in=schedule.lead_in,
        end_time=schedule.end_time(default_lead_in).isoformat() if schedule.start_time and schedule.runtime else None,
        runtime=schedule.runtime,
        status=schedule.status,
        last_error=schedule.last_error or None,
        created_at=schedule.created_at.isoformat(),
    )


@schedules_api.get(
    "/list",
    response={
        200: ScheduleListResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def list_schedules(request: HttpRequest, filters: ScheduleListFilters = Query(...)):
    """Get all schedules with filtering."""
    schedules = ProgrammeSchedule.objects.select_related("programme").all()
    default = default_lead_in()

    if not filters.show_past:
        now = timezone.now()
        past_schedule_ids = []

        for schedule in schedules:
            if schedule.start_time and schedule.runtime and schedule.end_time(default) <= now:
                past_schedule_ids.append(schedule.id)

        if past_schedule_ids:
            schedules = schedules.exclude(id__in=past_schedule_ids)

    if filters.status:
        schedules = schedules.filter(status=filters.status)

    if filters.programme_id:
        schedules = schedules.filter(programme_id=filters.programme_id)

    if filters.date_from:
        try:
            date_from_parsed = datetime.fromisoformat(filters.date_from.replace("Z", "+00:00"))
            schedules = schedules.filter(start_time__gte=date_from_parsed)
        except ValueError:
            raise ValidationError(
                "Invalid date_from format. Use ISO format.", error_code="INVALID_DATE_FORMAT"
            ) from None

    if filters.date_to:
        try:
            date_to_parsed = datetime.fromisoformat(filters.date_to.replace("Z", "+00:00"))
            schedules = schedules.filter(start_time__lte=date_to_parsed)
        except ValueError:
            raise ValidationError("Invalid date_to format. Use ISO format.", error_code="INVALID_DATE_FORMAT") from None

    schedules = schedules.order_by("start_time")

    schedules_data = [serialize_schedule(schedule, default) for schedule in schedules]

    return Status(
        200,
        ScheduleListResponseSchema(
            message="Schedules retrieved successfully",
            data=ScheduleListDataSchema(schedules=schedules_data, count=len(schedules_data), default_lead_in=default),
        ),
    )


@schedules_api.post(
    "/create",
    response={
        201: ScheduleCreateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def create_schedule(request: HttpRequest, data: CreateScheduleSchema):
    try:
        programme = Programme.objects.get(id=data.programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

    runtime = programme.get_runtime()

    try:
        tz = pytz.timezone(data.timezone)
    except Exception:
        tz = pytz.UTC

    try:
        naive_dt = datetime.fromisoformat(data.start_time.replace("Z", ""))
        local_dt = tz.localize(naive_dt)
    except ValueError:
        raise ValidationError("Invalid start_time format. Use ISO format.", error_code="INVALID_DATE_FORMAT") from None

    start_time_dt = local_dt.astimezone(pytz.UTC)

    if start_time_dt <= timezone.now():
        raise ValidationError("Start time must be in the future", error_code="INVALID_START_TIME")

    schedule = ProgrammeSchedule(programme=programme, start_time=start_time_dt, runtime=runtime, lead_in=data.lead_in)
    _reject_overlap(schedule)
    schedule.save()

    return Status(
        201,
        ScheduleCreateResponseSchema(
            message="Schedule created successfully", data=ScheduleDataSchema(schedule=serialize_schedule(schedule))
        ),
    )


@schedules_api.delete(
    "/{schedule_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_schedule(request: HttpRequest, schedule_id: int):
    try:
        schedule = ProgrammeSchedule.objects.get(id=schedule_id)
    except ProgrammeSchedule.DoesNotExist:
        raise NotFoundError("Schedule not found", error_code="SCHEDULE_NOT_FOUND") from None

    schedule.delete()

    return Status(200, MessageResponseSchema(message="Schedule deleted successfully"))


@schedules_api.put(
    "/{schedule_id}",
    response={
        200: ScheduleCreateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def update_schedule(request: HttpRequest, schedule_id: int, data: UpdateScheduleSchema):
    try:
        schedule = ProgrammeSchedule.objects.get(id=schedule_id)
    except ProgrammeSchedule.DoesNotExist:
        raise NotFoundError("Schedule not found", error_code="SCHEDULE_NOT_FOUND") from None

    if schedule.status != "scheduled":
        raise ValidationError("Can only update scheduled items", error_code="INVALID_SCHEDULE_STATUS")

    try:
        tz = pytz.timezone(data.timezone)
    except Exception:
        tz = pytz.UTC

    try:
        naive_dt = datetime.fromisoformat(data.start_time.replace("Z", ""))
        local_dt = tz.localize(naive_dt)
    except ValueError:
        raise ValidationError("Invalid start_time format. Use ISO format.", error_code="INVALID_DATE_FORMAT") from None

    new_start_time_dt = local_dt.astimezone(pytz.UTC)

    if new_start_time_dt <= timezone.now():
        raise ValidationError("Start time must be in the future", error_code="INVALID_START_TIME")

    # Refresh the runtime snapshot too — the programme's blocks may have changed,
    # and a stale runtime drives end_time() (and the past-schedule filter) wrongly.
    schedule.start_time = new_start_time_dt
    schedule.runtime = schedule.programme.get_runtime()
    schedule.lead_in = data.lead_in
    _reject_overlap(schedule)
    schedule.save(update_fields=["start_time", "runtime", "lead_in"])

    return Status(
        200,
        ScheduleCreateResponseSchema(
            message="Schedule updated successfully", data=ScheduleDataSchema(schedule=serialize_schedule(schedule))
        ),
    )
