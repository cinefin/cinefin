import logging
from datetime import datetime

import pytz
from django.http import HttpRequest
from django.utils import timezone
from ninja import Field, Query, Router, Schema, Status

from cinefin.api.exceptions import ConflictError, ValidationError, get_or_404
from cinefin.api.models import Programme, ProgrammeSchedule
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import preshow

logger = logging.getLogger(__name__)


class ProgrammeBasicSchema(Schema):
    id: int
    name: str
    runtime: int
    formatted_runtime: str | None = Field(None, description="Human-readable formatted runtime")
    description: str | None = None


class LeadInStepSchema(Schema):
    command: int | None = Field(default=None, description="Command ID to run (omit for the cue step)")
    cue: bool = Field(default=False, description="The step that cues the programme and holds its title slate")


class ScheduleSchema(Schema):
    id: int
    programme: ProgrammeBasicSchema
    start_time: str = Field(..., description="When the lead-in begins (ISO)")
    play_time: str = Field(..., description="When the programme plays: start_time + lead-in (ISO)")
    lead_in: int = Field(0, description="Seconds between the lead-in starting and the programme playing")
    preshow: list[LeadInStepSchema] = Field(
        default_factory=list, description="The lead-in's ordered steps: commands plus the one cue step"
    )
    runtime: int
    status: str = Field(..., description="Schedule status (scheduled, running, completed, cancelled, failed, missed)")
    last_error: str | None = Field(None, description="Reason the run failed, if any")
    created_at: str
    end_time: str | None = Field(None, description="When the screening ends: play_time + runtime (ISO)")


class ScheduleListFilters(Schema):
    status: str | None = None
    programme_id: int | None = None
    date_from: str | None = Field(None, description="Filter schedules from this date (ISO format)")
    date_to: str | None = Field(None, description="Filter schedules to this date (ISO format)")
    show_past: bool = False


class ScheduleListDataSchema(Schema):
    schedules: list[ScheduleSchema]
    count: int


class ScheduleListResponseSchema(SuccessResponseSchema):
    data: ScheduleListDataSchema


class UpdateScheduleSchema(Schema):
    start_time: str = Field(..., description="When the lead-in begins, in ISO format")
    timezone: str = Field("UTC", description="Timezone for the start time")
    lead_in: int = Field(0, ge=0, description="Seconds between the lead-in starting and the programme playing")
    preshow: list[LeadInStepSchema] = Field(
        default_factory=list, description="The lead-in's ordered steps; none = just the cue"
    )


class CreateScheduleSchema(UpdateScheduleSchema):
    programme_id: int


class ScheduleDataSchema(Schema):
    schedule: ScheduleSchema


class ScheduleCreateResponseSchema(SuccessResponseSchema):
    data: ScheduleDataSchema


class RunnerStatusSchema(Schema):
    running: bool
    pid: int | None = None
    last_beat: str | None = Field(None, description="Last heartbeat (ISO)")
    age_seconds: float | None = None
    tick_seconds: int | None = None


class RunnerStatusResponseSchema(SuccessResponseSchema):
    data: RunnerStatusSchema


schedules_api = Router()


def _reject_overlap(schedule: ProgrammeSchedule) -> None:
    """A screening occupies start_time (lead-in) → end_time; two active ones may not overlap."""
    start, end = schedule.start_time, schedule.end_time()
    others = ProgrammeSchedule.objects.filter(status__in=["scheduled", "running"], start_time__lt=end).exclude(
        id=schedule.id
    )
    clash = next((o for o in others.select_related("programme") if o.end_time() > start), None)
    if clash:
        raise ConflictError(
            f"Overlaps “{clash.programme.name}” "
            f"({timezone.localtime(clash.start_time):%H:%M}–{timezone.localtime(clash.end_time()):%H:%M})",
            error_code="SCHEDULE_OVERLAP",
            details={"schedule_id": clash.id},
        )


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


def serialize_schedule(schedule: ProgrammeSchedule) -> ScheduleSchema:
    return ScheduleSchema(
        id=schedule.id,
        programme=serialize_programme_basic(schedule.programme),
        start_time=schedule.start_time.isoformat(),
        play_time=schedule.play_time().isoformat(),
        lead_in=schedule.lead_in,
        preshow=[
            LeadInStepSchema(cue=True) if s == preshow.CUE else LeadInStepSchema(command=s)
            for s in preshow.steps(schedule.preshow)
        ],
        end_time=schedule.end_time().isoformat() if schedule.start_time and schedule.runtime else None,
        runtime=schedule.runtime,
        status=schedule.status,
        last_error=schedule.last_error or None,
        created_at=schedule.created_at.isoformat(),
    )


def _parse_filter_date(value: str, name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"Invalid {name} format. Use ISO format.", error_code="INVALID_DATE_FORMAT") from None


def _future_start(data: UpdateScheduleSchema) -> datetime:
    """The schedule's start time in UTC: read in its timezone (an unknown one is UTC), refused unless future."""
    try:
        tz = pytz.timezone(data.timezone)
    except Exception:
        tz = pytz.UTC
    try:
        start = tz.localize(datetime.fromisoformat(data.start_time.replace("Z", ""))).astimezone(pytz.UTC)
    except ValueError:
        raise ValidationError("Invalid start_time format. Use ISO format.", error_code="INVALID_DATE_FORMAT") from None
    if start <= timezone.now():
        raise ValidationError("Start time must be in the future", error_code="INVALID_START_TIME")
    return start


def _saved(status: int, message: str, schedule: ProgrammeSchedule) -> Status:
    return Status(
        status,
        ScheduleCreateResponseSchema(message=message, data=ScheduleDataSchema(schedule=serialize_schedule(schedule))),
    )


_WRITE_ERRORS = {
    400: ErrorResponseSchema,
    404: ErrorResponseSchema,
    409: ErrorResponseSchema,
    422: ErrorResponseSchema,
    500: ErrorResponseSchema,
}


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
    schedules = ProgrammeSchedule.objects.select_related("programme").all()
    if not filters.show_past:
        now = timezone.now()
        past = [s.id for s in schedules if s.start_time and s.runtime and s.end_time() <= now]
        if past:
            schedules = schedules.exclude(id__in=past)
    if filters.status:
        schedules = schedules.filter(status=filters.status)
    if filters.programme_id:
        schedules = schedules.filter(programme_id=filters.programme_id)
    if filters.date_from:
        schedules = schedules.filter(start_time__gte=_parse_filter_date(filters.date_from, "date_from"))
    if filters.date_to:
        schedules = schedules.filter(start_time__lte=_parse_filter_date(filters.date_to, "date_to"))
    schedules_data = [serialize_schedule(s) for s in schedules.order_by("start_time")]
    return Status(
        200,
        ScheduleListResponseSchema(
            message="Schedules retrieved successfully",
            data=ScheduleListDataSchema(schedules=schedules_data, count=len(schedules_data)),
        ),
    )


@schedules_api.post("/create", response={201: ScheduleCreateResponseSchema, **_WRITE_ERRORS})
def create_schedule(request: HttpRequest, data: CreateScheduleSchema):
    programme = get_or_404(Programme, data.programme_id, "Programme not found", "PROGRAMME_NOT_FOUND")
    schedule = ProgrammeSchedule(
        programme=programme,
        start_time=_future_start(data),
        runtime=programme.get_runtime(),
        lead_in=data.lead_in,
        preshow=preshow.clean([step.dict() for step in data.preshow]),
    )
    _reject_overlap(schedule)
    schedule.save()
    return _saved(201, "Schedule created successfully", schedule)


@schedules_api.delete(
    "/{schedule_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_schedule(request: HttpRequest, schedule_id: int):
    get_or_404(ProgrammeSchedule, schedule_id, "Schedule not found", "SCHEDULE_NOT_FOUND").delete()
    return Status(200, MessageResponseSchema(message="Schedule deleted successfully"))


@schedules_api.put("/{schedule_id}", response={200: ScheduleCreateResponseSchema, **_WRITE_ERRORS})
def update_schedule(request: HttpRequest, schedule_id: int, data: UpdateScheduleSchema):
    schedule = get_or_404(ProgrammeSchedule, schedule_id, "Schedule not found", "SCHEDULE_NOT_FOUND")
    if schedule.status != "scheduled":
        raise ValidationError("Can only update scheduled items", error_code="INVALID_SCHEDULE_STATUS")
    schedule.start_time = _future_start(data)
    # Refresh the runtime snapshot: the programme's blocks may have changed, and a stale
    # runtime drives end_time() (and the past-schedule filter) wrongly.
    schedule.runtime = schedule.programme.get_runtime()
    schedule.lead_in = data.lead_in
    schedule.preshow = preshow.clean([step.dict() for step in data.preshow])
    _reject_overlap(schedule)
    schedule.save(update_fields=["start_time", "runtime", "lead_in", "preshow"])
    return _saved(200, "Schedule updated successfully", schedule)
