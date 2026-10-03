import datetime
import logging
import os
from typing import Literal

from django.http import FileResponse, HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Programme, ProgrammeSchedule, Settings, TicketDesign, TicketIssue
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.schemas.tickets import Element
from cinefin.api.services import ticket_service

logger = logging.getLogger(__name__)


def _print_or_422(design, ctx):
    try:
        ticket_service.print_ticket(design, ctx)
    except RuntimeError as e:
        raise UnprocessableEntityError(f"Failed to print ticket — {e}", error_code="PRINTER_ERROR") from e


def _print_run_or_422(**run_fields):
    try:
        return ticket_service.print_run(**run_fields)
    except RuntimeError as e:
        raise UnprocessableEntityError(f"Failed to print ticket — {e}", error_code="PRINTER_ERROR") from e


def _resolve_schedule(schedule_id: int | None, programme: Programme | None = None) -> ProgrammeSchedule | None:
    if not schedule_id:
        return None
    try:
        schedule = ProgrammeSchedule.objects.get(pk=schedule_id)
    except ProgrammeSchedule.DoesNotExist:
        raise NotFoundError("Schedule not found", error_code="SCHEDULE_NOT_FOUND") from None
    if programme is not None and schedule.programme_id != programme.id:
        raise ValidationError("Schedule does not belong to this programme", error_code="SCHEDULE_PROGRAMME_MISMATCH")
    return schedule


def _validate_seat(seat: str | None):
    if seat and not validate_seat_format(seat):
        raise ValidationError("Invalid seat format. Use format like A15, B12, etc.", error_code="INVALID_SEAT_FORMAT")


class CustomTicketRequestSchema(Schema):
    text: str
    seat: str | None = None
    copies: int = Field(1, ge=1, le=10, description="Number of tickets to print, each with its own seat")


class TicketSettingsUpdateSchema(Schema):
    ticket_total_rows: int | None = None
    ticket_seats_per_row: int | None = None


class DesignDraftSchema(Schema):
    """A design's content as the designer holds it; anything left out takes the default."""

    elements: list[Element] = Field(default_factory=list)
    date_format: str | None = Field(None, description="strftime preset (ticket_service.DATE_FORMATS)")
    time_format: str | None = Field(None, description="strftime preset (ticket_service.TIME_FORMATS)")
    qr_links: list[str] | None = Field(None, description="Links a surprise QR picks from (empty = no QR)")
    font: str | None = Field(None, description="Font of the design's columns rows (ticket_service.TICKET_FONTS)")


class TestTicketRequestSchema(Schema):
    include_seat: bool = True
    design: DesignDraftSchema | None = Field(
        None, description="Print this draft with the preview's sample details (else the default design)"
    )


class ProgrammeTicketRequestSchema(Schema):
    seat: str | None = None
    seats: list[str] | None = Field(None, description="Explicit seats — one ticket each (overrides seat/copies)")
    schedule_id: int | None = Field(None, description="Print the schedule's showtime and track seats against it")
    copies: int = Field(1, ge=1, le=20, description="Number of tickets to print, each with its own seat")


class TicketPreviewRequestSchema(Schema):
    design: DesignDraftSchema | None = Field(
        None, description="A draft design to preview (else design_id, else default)"
    )
    design_id: int | None = Field(None, description="Preview a saved design")
    seat: str | None = Field(None, description="Seat to show (sampled when omitted)")


class PreviewItemSchema(Schema):
    y: int
    h: int = Field(..., description="0 when the item prints nothing")


class PreviewCellSchema(Schema):
    x: int
    w: int
    items: list[PreviewItemSchema]


class PreviewLineSchema(Schema):
    element: int = Field(..., description="Index of the design element this line is")
    y: int
    h: int
    empty: bool = Field(False, description="Prints nothing: a grey placeholder in the preview only")
    cells: list[PreviewCellSchema] | None = Field(None, description="A columns line's cells and their items")


class TicketPreviewDataSchema(Schema):
    url: str = Field(..., description="The ticket drawn as it prints, as a PNG data URL, 1 px per printer dot")
    width: int = Field(..., description="Printable width in dots")
    height: int
    lines: list[PreviewLineSchema] = Field(..., description="Where each line sits on the image, in dots")


class TicketPreviewResponseSchema(SuccessResponseSchema):
    data: TicketPreviewDataSchema = Field(..., description="Ticket preview")


class TicketPrintDataSchema(Schema):
    seat: str | None = Field(None, description="Seat of the first printed ticket")
    seats: list[str] = Field(default_factory=list, description="Seat of every printed ticket, in print order")
    ticket_numbers: list[int] = Field(default_factory=list, description="Issued ticket numbers, in print order")
    copies: int = Field(1, description="Number of tickets printed")
    text: str | None = Field(None, description="Custom ticket text")


class TicketPrintResponseSchema(SuccessResponseSchema):
    data: TicketPrintDataSchema = Field(..., description="Ticket print data")


class TicketIssueSchema(Schema):
    id: int
    ticket_number: int
    seat: str
    title: str
    kind: str
    printed_at: datetime.datetime
    programme_id: int | None = None
    movie_id: int | None = None
    schedule_id: int | None = None


class TicketIssuedDataSchema(Schema):
    tickets: list[TicketIssueSchema] = Field(..., description="Issued tickets, newest first")
    count: int = Field(..., description="Total number of issued tickets matching the filter")


class TicketIssuedResponseSchema(SuccessResponseSchema):
    data: TicketIssuedDataSchema = Field(..., description="Issued-ticket history")


class SeatMapDataSchema(Schema):
    rows: int = Field(..., description="Number of seat rows (A…)")
    seats_per_row: int = Field(..., description="Seats per row")
    occupied: list[str] = Field(..., description="Seats already ticketed for this programme/schedule")


class SeatMapResponseSchema(SuccessResponseSchema):
    data: SeatMapDataSchema = Field(..., description="Seat map with occupancy")


class TicketSettingsSchema(Schema):
    cinema_name: str
    ticket_total_rows: int
    ticket_seats_per_row: int
    total_seats: int


class TicketSettingsDataSchema(Schema):
    settings: TicketSettingsSchema = Field(..., description="Ticket settings")


class TicketSettingsResponseSchema(SuccessResponseSchema):
    data: TicketSettingsDataSchema = Field(..., description="Ticket settings data")


ticket_api = Router()


def get_next_available_seat(programme=None, schedule=None):
    return ticket_service.next_available_seat(programme=programme, schedule=schedule)


def validate_seat_format(seat: str) -> bool:
    if not seat:
        return True
    return len(seat) >= 2 and seat[0].isalpha() and seat[1:].isdigit()


@ticket_api.post(
    "/print/programme/{programme_id}",
    response={
        200: TicketPrintResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def print_programme_ticket(request: HttpRequest, programme_id: int, data: ProgrammeTicketRequestSchema):
    try:
        programme = Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

    schedule = _resolve_schedule(data.schedule_id, programme)
    _validate_seat(data.seat)
    for s in data.seats or []:
        _validate_seat(s)

    issues = _print_run_or_422(
        kind=TicketIssue.KIND_PROGRAMME,
        title=programme.name,
        design=ticket_service.resolve_ticket_design(programme),
        copies=data.copies,
        seat=data.seat,
        seats=data.seats,
        programme=programme,
        schedule=schedule,
        when=schedule.play_time() if schedule else None,
        scheduled=schedule is not None,
        programme_name=programme.name,
        features=ticket_service.programme_features(programme),
    )

    seats = [issue.seat for issue in issues]
    return Status(
        200,
        TicketPrintResponseSchema(
            message="Programme ticket printed successfully"
            if len(issues) == 1
            else f"{len(issues)} programme tickets printed successfully",
            data=TicketPrintDataSchema(
                seat=seats[0],
                seats=seats,
                ticket_numbers=[issue.ticket_number for issue in issues],
                copies=len(issues),
            ),
        ),
    )


@ticket_api.post(
    "/print/custom",
    response={
        200: TicketPrintResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def print_custom_ticket(request: HttpRequest, data: CustomTicketRequestSchema):
    if not data.text:
        raise ValidationError("No text provided for custom ticket", error_code="CUSTOM_TEXT_REQUIRED")

    _validate_seat(data.seat)

    issues = _print_run_or_422(
        kind=TicketIssue.KIND_CUSTOM,
        title=data.text.splitlines()[0] if data.text.splitlines() else "",
        design=[{"type": "text", "content": data.text}],
        copies=data.copies,
        seat=data.seat,
    )

    seats = [issue.seat for issue in issues]
    return Status(
        200,
        TicketPrintResponseSchema(
            message="Custom ticket printed successfully"
            if len(issues) == 1
            else f"{len(issues)} custom tickets printed successfully",
            data=TicketPrintDataSchema(
                seat=seats[0],
                seats=seats,
                ticket_numbers=[issue.ticket_number for issue in issues],
                copies=len(issues),
                text=data.text,
            ),
        ),
    )


@ticket_api.get("/settings", response={200: TicketSettingsResponseSchema, 500: ErrorResponseSchema})
def get_ticket_settings(request: HttpRequest):
    cinema_name = Settings.get("cinema.name", "Cinefin")
    ticket_total_rows = Settings.get("tickets.total_rows", 10)
    ticket_seats_per_row = Settings.get("tickets.seats_per_row", 20)

    return Status(
        200,
        TicketSettingsResponseSchema(
            message="Ticket settings retrieved successfully",
            data=TicketSettingsDataSchema(
                settings=TicketSettingsSchema(
                    cinema_name=cinema_name,
                    ticket_total_rows=ticket_total_rows,
                    ticket_seats_per_row=ticket_seats_per_row,
                    total_seats=ticket_total_rows * ticket_seats_per_row,
                )
            ),
        ),
    )


@ticket_api.post(
    "/settings/update", response={200: MessageResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def update_ticket_settings(request: HttpRequest, data: TicketSettingsUpdateSchema):
    if data.ticket_total_rows is not None:
        rows = data.ticket_total_rows
        if not (1 <= rows <= 26):
            raise ValidationError("Total rows must be between 1 and 26", error_code="INVALID_ROWS_COUNT")
        Settings.set("tickets.total_rows", rows)

    if data.ticket_seats_per_row is not None:
        seats = data.ticket_seats_per_row
        if not (1 <= seats <= 100):
            raise ValidationError("Seats per row must be between 1 and 100", error_code="INVALID_SEATS_PER_ROW")
        Settings.set("tickets.seats_per_row", seats)

    return Status(200, MessageResponseSchema(message="Ticket settings updated successfully"))


@ticket_api.post("/test", response=TicketPrintResponseSchema)
def test_ticket_print(request: HttpRequest, data: TestTicketRequestSchema):
    seat = get_next_available_seat() if data.include_seat else None

    if data.design is not None:
        # The designer's test print: the design being edited, filled in as its preview is.
        draft = ticket_service.validate_design(data.design.dict())
        seat = seat or get_next_available_seat()
        _print_or_422(draft, _sample_context(seat))
    else:
        ctx = ticket_service.make_ticket_context(features=[{"title": "Test Ticket"}], seat=seat, ticket_no=0)
        _print_or_422(ticket_service.resolve_ticket_design(None), ctx)

    return TicketPrintResponseSchema(
        message="Test ticket printed successfully",
        data=TicketPrintDataSchema(seat=seat, seats=[seat] if seat else [], copies=1),
    )


@ticket_api.post("/reset", response={200: MessageResponseSchema, 422: ErrorResponseSchema})
def reset_printer(request: HttpRequest):
    """Recover a printer left in a bad state (ESC @ + feed) instead of a power-cycle."""
    try:
        ticket_service.reset_printer()
    except RuntimeError as e:
        raise UnprocessableEntityError(f"Failed to reset printer — {e}", error_code="PRINTER_ERROR") from e
    return Status(200, MessageResponseSchema(message="Printer reset — try printing again"))


@ticket_api.post(
    "/reprint/{issue_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema}
)
def reprint_ticket(request: HttpRequest, issue_id: int):
    """Reprint an issued ticket exactly as it was; records nothing new."""
    try:
        issue = TicketIssue.objects.get(pk=issue_id)
    except TicketIssue.DoesNotExist:
        raise NotFoundError("Ticket not found", error_code="TICKET_NOT_FOUND") from None
    try:
        ticket_service.reprint_issue(issue)
    except RuntimeError as e:
        raise UnprocessableEntityError(f"Failed to reprint ticket — {e}", error_code="PRINTER_ERROR") from e
    return Status(200, MessageResponseSchema(message=f"Reprinted ticket #{issue.ticket_number}"))


@ticket_api.get("/issued", response={200: TicketIssuedResponseSchema, 404: ErrorResponseSchema})
def list_issued_tickets(request: HttpRequest, programme_id: int | None = None):
    issues = TicketIssue.objects.all()
    if programme_id is not None:
        if not Programme.objects.filter(pk=programme_id).exists():
            raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND")
        issues = issues.filter(programme_id=programme_id)

    tickets = [
        TicketIssueSchema(
            id=issue.id,
            ticket_number=issue.ticket_number,
            seat=issue.seat,
            title=issue.title,
            kind=issue.kind,
            printed_at=issue.printed_at,
            programme_id=issue.programme_id,
            movie_id=issue.movie_id,
            schedule_id=issue.schedule_id,
        )
        for issue in issues
    ]
    return Status(
        200,
        TicketIssuedResponseSchema(
            message="Issued tickets retrieved successfully",
            data=TicketIssuedDataSchema(tickets=tickets, count=len(tickets)),
        ),
    )


@ticket_api.get("/seats", response={200: SeatMapResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema})
def get_seat_map(request: HttpRequest, programme_id: int, schedule_id: int | None = None):
    try:
        programme = Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None
    schedule = _resolve_schedule(schedule_id, programme)

    issues = TicketIssue.objects.filter(programme=programme).exclude(seat="")
    if schedule is not None:
        issues = issues.filter(schedule=schedule)

    return Status(
        200,
        SeatMapResponseSchema(
            message="Seat map retrieved successfully",
            data=SeatMapDataSchema(
                rows=Settings.get("tickets.total_rows", 10),
                seats_per_row=Settings.get("tickets.seats_per_row", 20),
                occupied=sorted(set(issues.values_list("seat", flat=True))),
            ),
        ),
    )


def _sample_context(seat: str) -> dict:
    """The made-up programme the designer previews and test-prints a design with."""
    year = datetime.datetime.now().year
    certs = ("PG", "15") if Settings.get_ratings_system() == "BBFC" else ("PG", "PG-13")
    return ticket_service.make_ticket_context(
        seat=seat,
        ticket_no=142,
        programme_name="Sample Programme",
        features=[
            {"title": "Sample Feature", "year": year, "certification": certs[1]},
            {"title": "Second Feature", "year": year - 1, "certification": certs[0]},
        ],
    )


@ticket_api.post(
    "/preview", response={200: TicketPreviewResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema}
)
def preview_ticket(request: HttpRequest, data: TicketPreviewRequestSchema):
    if data.design is not None:
        design = ticket_service.validate_design(data.design.dict())
    elif data.design_id:
        try:
            design = TicketDesign.objects.get(pk=data.design_id)
        except TicketDesign.DoesNotExist:
            raise NotFoundError("Ticket design not found", error_code="DESIGN_NOT_FOUND") from None
    else:
        design = ticket_service.resolve_ticket_design(None)

    preview = ticket_service.preview_ticket(design, _sample_context(data.seat or get_next_available_seat()))
    return Status(200, TicketPreviewResponseSchema(message="Ticket preview", data=TicketPreviewDataSchema(**preview)))


@ticket_api.get("/preview/asset", response={404: ErrorResponseSchema})
def preview_asset(request: HttpRequest, kind: str, file: str | None = None):
    """Stream a ticket-library image, for the image library's thumbnails (the library isn't web-served)."""
    if kind != "image":
        raise ValidationError("kind must be 'image'", error_code="INVALID_ASSET_KIND")
    path = ticket_service.ticket_image_path(file)
    if not path or not os.path.exists(path):
        raise NotFoundError("Ticket asset not found", error_code="TICKET_ASSET_NOT_FOUND")
    return FileResponse(open(path, "rb"))  # content type inferred from the filename


class DesignSummarySchema(Schema):
    id: int
    name: str
    is_default: bool


DESIGN_FIELDS = ("elements", "date_format", "time_format", "qr_links", "font")


class DesignSchema(Schema):
    id: int
    name: str
    is_default: bool
    elements: list[Element]
    date_format: str
    time_format: str
    qr_links: list[str]
    font: str


class DesignCreateSchema(Schema):
    name: str = Field(..., min_length=1, max_length=120)
    starter: Literal["standard", "compact", "blank"] = Field("standard", description="The layout it starts from")


class DesignUpdateSchema(Schema):
    name: str | None = Field(None, min_length=1, max_length=120)
    elements: list[Element] | None = None
    date_format: str | None = None
    time_format: str | None = None
    qr_links: list[str] | None = None
    font: str | None = None
    is_default: bool | None = None


def _design_out(d: TicketDesign) -> DesignSchema:
    return DesignSchema(id=d.id, name=d.name, is_default=d.is_default, **{k: getattr(d, k) for k in DESIGN_FIELDS})


@ticket_api.get("/designs", response=list[DesignSummarySchema])
def list_designs(request: HttpRequest):
    TicketDesign.get_default()
    return [DesignSummarySchema(id=d.id, name=d.name, is_default=d.is_default) for d in TicketDesign.objects.all()]


@ticket_api.get("/designs/{int:design_id}", response={200: DesignSchema, 404: ErrorResponseSchema})
def get_design(request: HttpRequest, design_id: int):
    try:
        return _design_out(TicketDesign.objects.get(pk=design_id))
    except TicketDesign.DoesNotExist:
        raise NotFoundError("Ticket design not found", error_code="DESIGN_NOT_FOUND") from None


@ticket_api.post("/designs", response={200: DesignSchema, 400: ErrorResponseSchema})
def create_design(request: HttpRequest, data: DesignCreateSchema):
    elements = ticket_service.dump_elements(ticket_service.parse_elements(ticket_service.STARTER_DESIGNS[data.starter]))
    is_first = not TicketDesign.objects.exists()
    design = TicketDesign.objects.create(name=data.name.strip(), elements=elements, is_default=is_first)
    return _design_out(design)


@ticket_api.put(
    "/designs/{int:design_id}", response={200: DesignSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema}
)
def update_design(request: HttpRequest, design_id: int, data: DesignUpdateSchema):
    try:
        design = TicketDesign.objects.get(pk=design_id)
    except TicketDesign.DoesNotExist:
        raise NotFoundError("Ticket design not found", error_code="DESIGN_NOT_FOUND") from None
    if data.name is not None:
        design.name = data.name.strip()
    for key, value in ticket_service.validate_design(data.dict()).items():
        setattr(design, key, value)
    if data.is_default:
        design.is_default = True  # save() demotes the others
    design.save()
    return _design_out(design)


@ticket_api.post("/designs/{int:design_id}/duplicate", response={200: DesignSchema, 404: ErrorResponseSchema})
def duplicate_design(request: HttpRequest, design_id: int):
    try:
        src = TicketDesign.objects.get(pk=design_id)
    except TicketDesign.DoesNotExist:
        raise NotFoundError("Ticket design not found", error_code="DESIGN_NOT_FOUND") from None
    copy = TicketDesign.objects.create(name=f"{src.name} copy", **{k: getattr(src, k) for k in DESIGN_FIELDS})
    return _design_out(copy)


@ticket_api.delete(
    "/designs/{int:design_id}",
    response={200: MessageResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema},
)
def delete_design(request: HttpRequest, design_id: int):
    try:
        design = TicketDesign.objects.get(pk=design_id)
    except TicketDesign.DoesNotExist:
        raise NotFoundError("Ticket design not found", error_code="DESIGN_NOT_FOUND") from None
    if TicketDesign.objects.count() <= 1:
        raise ValidationError("Can't delete the only ticket design", error_code="LAST_DESIGN")
    was_default = design.is_default
    design.delete()
    if was_default:
        TicketDesign.get_default()
    return Status(200, MessageResponseSchema(message="Ticket design deleted"))


class ProgrammeDesignSchema(Schema):
    design_id: int | None = Field(None, description="Design to use, or null for the default")


@ticket_api.get(
    "/programmes/{int:programme_id}/design", response={200: ProgrammeDesignSchema, 404: ErrorResponseSchema}
)
def get_programme_design(request: HttpRequest, programme_id: int):
    try:
        programme = Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None
    return ProgrammeDesignSchema(design_id=programme.ticket_design_id)


@ticket_api.post(
    "/programmes/{int:programme_id}/design", response={200: MessageResponseSchema, 404: ErrorResponseSchema}
)
def set_programme_design(request: HttpRequest, programme_id: int, data: ProgrammeDesignSchema):
    try:
        programme = Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None
    if data.design_id is None:
        programme.ticket_design = None
    else:
        try:
            programme.ticket_design = TicketDesign.objects.get(pk=data.design_id)
        except TicketDesign.DoesNotExist:
            raise NotFoundError("Ticket design not found", error_code="DESIGN_NOT_FOUND") from None
    programme.save(update_fields=["ticket_design"])
    return Status(200, MessageResponseSchema(message="Ticket design updated"))
