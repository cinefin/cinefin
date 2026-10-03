"""Tickets API — printing, issued-ticket history, seat maps and ticket designs."""

import datetime
import os
from contextlib import contextmanager
from typing import Literal

from django.http import FileResponse, HttpRequest
from ninja import Field, Router, Schema

from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Programme, ProgrammeSchedule, Settings, TicketDesign, TicketIssue
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.schemas.tickets import Element
from cinefin.api.services import ticket_service

E404 = {404: ErrorResponseSchema}


@contextmanager
def _printer_errors(action: str = "print ticket"):
    try:
        yield
    except RuntimeError as e:
        raise UnprocessableEntityError(f"Failed to {action} — {e}", error_code="PRINTER_ERROR") from e


def _get_programme(programme_id: int) -> Programme:
    try:
        return Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None


def _get_design(design_id: int) -> TicketDesign:
    try:
        return TicketDesign.objects.get(pk=design_id)
    except TicketDesign.DoesNotExist:
        raise NotFoundError("Ticket design not found", error_code="DESIGN_NOT_FOUND") from None


def _resolve_schedule(schedule_id: int | None, programme: Programme) -> ProgrammeSchedule | None:
    if not schedule_id:
        return None
    try:
        schedule = ProgrammeSchedule.objects.get(pk=schedule_id)
    except ProgrammeSchedule.DoesNotExist:
        raise NotFoundError("Schedule not found", error_code="SCHEDULE_NOT_FOUND") from None
    if schedule.programme_id != programme.id:
        raise ValidationError("Schedule does not belong to this programme", error_code="SCHEDULE_PROGRAMME_MISMATCH")
    return schedule


def _validate_seat(seat: str | None):
    if seat and not (len(seat) >= 2 and seat[0].isalpha() and seat[1:].isdigit()):
        raise ValidationError("Invalid seat format. Use format like A15, B12, etc.", error_code="INVALID_SEAT_FORMAT")


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
    data: TicketPreviewDataSchema


class TicketPrintDataSchema(Schema):
    seat: str | None = Field(None, description="Seat of the first printed ticket")
    seats: list[str] = Field(default_factory=list, description="Seat of every printed ticket, in print order")
    ticket_numbers: list[int] = Field(default_factory=list, description="Issued ticket numbers, in print order")
    copies: int = 1
    text: str | None = None


class TicketPrintResponseSchema(SuccessResponseSchema):
    data: TicketPrintDataSchema


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
    tickets: list[TicketIssueSchema] = Field(..., description="Newest first")
    count: int


class TicketIssuedResponseSchema(SuccessResponseSchema):
    data: TicketIssuedDataSchema


class SeatMapDataSchema(Schema):
    rows: int = Field(..., description="Number of seat rows (A…)")
    seats_per_row: int
    occupied: list[str] = Field(..., description="Seats already ticketed for this programme/schedule")


class SeatMapResponseSchema(SuccessResponseSchema):
    data: SeatMapDataSchema


ticket_api = Router()


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
    programme = _get_programme(programme_id)
    schedule = _resolve_schedule(data.schedule_id, programme)
    for seat in [data.seat, *(data.seats or [])]:
        _validate_seat(seat)

    with _printer_errors():
        issues = ticket_service.print_run(
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
    return {
        "message": "Programme ticket printed successfully"
        if len(issues) == 1
        else f"{len(issues)} programme tickets printed successfully",
        "data": {
            "seat": seats[0],
            "seats": seats,
            "ticket_numbers": [issue.ticket_number for issue in issues],
            "copies": len(issues),
        },
    }


@ticket_api.post("/test", response=TicketPrintResponseSchema)
def test_ticket_print(request: HttpRequest, data: TestTicketRequestSchema):
    seat = ticket_service.next_available_seat() if data.include_seat else None
    if data.design is not None:
        # The designer's test print: the design being edited, filled in as its preview is.
        design = ticket_service.validate_design(data.design.dict())
        seat = seat or ticket_service.next_available_seat()
        ctx = _sample_context(seat)
    else:
        design = ticket_service.resolve_ticket_design(None)
        ctx = ticket_service.make_ticket_context(features=[{"title": "Test Ticket"}], seat=seat, ticket_no=0)
    with _printer_errors():
        ticket_service.print_ticket(design, ctx)
    return {
        "message": "Test ticket printed successfully",
        "data": {"seat": seat, "seats": [seat] if seat else [], "copies": 1},
    }


@ticket_api.post("/reset", response={200: MessageResponseSchema, 422: ErrorResponseSchema})
def reset_printer(request: HttpRequest):
    """Recover a printer left in a bad state (ESC @ + feed) instead of a power-cycle."""
    with _printer_errors("reset printer"):
        ticket_service.reset_printer()
    return {"message": "Printer reset — try printing again"}


@ticket_api.post("/reprint/{issue_id}", response={200: MessageResponseSchema, **E404, 422: ErrorResponseSchema})
def reprint_ticket(request: HttpRequest, issue_id: int):
    """Reprint an issued ticket exactly as it was; records nothing new."""
    try:
        issue = TicketIssue.objects.get(pk=issue_id)
    except TicketIssue.DoesNotExist:
        raise NotFoundError("Ticket not found", error_code="TICKET_NOT_FOUND") from None
    with _printer_errors("reprint ticket"):
        ticket_service.reprint_issue(issue)
    return {"message": f"Reprinted ticket #{issue.ticket_number}"}


@ticket_api.get("/issued", response={200: TicketIssuedResponseSchema, **E404})
def list_issued_tickets(request: HttpRequest, programme_id: int | None = None):
    issues = TicketIssue.objects.all()
    if programme_id is not None:
        issues = issues.filter(programme=_get_programme(programme_id))
    tickets = list(issues)
    return {
        "message": "Issued tickets retrieved successfully",
        "data": {"tickets": tickets, "count": len(tickets)},
    }


@ticket_api.get("/seats", response={200: SeatMapResponseSchema, 400: ErrorResponseSchema, **E404})
def get_seat_map(request: HttpRequest, programme_id: int, schedule_id: int | None = None):
    programme = _get_programme(programme_id)
    schedule = _resolve_schedule(schedule_id, programme)
    issues = TicketIssue.objects.filter(programme=programme).exclude(seat="")
    if schedule is not None:
        issues = issues.filter(schedule=schedule)
    return {
        "message": "Seat map retrieved successfully",
        "data": {
            "rows": Settings.get("tickets.total_rows", 10),
            "seats_per_row": Settings.get("tickets.seats_per_row", 20),
            "occupied": sorted(set(issues.values_list("seat", flat=True))),
        },
    }


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


@ticket_api.post("/preview", response={200: TicketPreviewResponseSchema, 400: ErrorResponseSchema, **E404})
def preview_ticket(request: HttpRequest, data: TicketPreviewRequestSchema):
    if data.design is not None:
        design = ticket_service.validate_design(data.design.dict())
    elif data.design_id:
        design = _get_design(data.design_id)
    else:
        design = ticket_service.resolve_ticket_design(None)
    preview = ticket_service.preview_ticket(design, _sample_context(data.seat or ticket_service.next_available_seat()))
    return {"message": "Ticket preview", "data": preview}


@ticket_api.get("/preview/asset", response=E404)
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


class ProgrammeDesignSchema(Schema):
    design_id: int | None = Field(None, description="Design to use, or null for the default")


@ticket_api.get("/designs", response=list[DesignSummarySchema])
def list_designs(request: HttpRequest):
    TicketDesign.get_default()
    return TicketDesign.objects.all()


@ticket_api.get("/designs/{int:design_id}", response={200: DesignSchema, **E404})
def get_design(request: HttpRequest, design_id: int):
    return _get_design(design_id)


@ticket_api.post("/designs", response={200: DesignSchema, 400: ErrorResponseSchema})
def create_design(request: HttpRequest, data: DesignCreateSchema):
    elements = ticket_service.dump_elements(ticket_service.parse_elements(ticket_service.STARTER_DESIGNS[data.starter]))
    is_first = not TicketDesign.objects.exists()
    return TicketDesign.objects.create(name=data.name.strip(), elements=elements, is_default=is_first)


@ticket_api.put("/designs/{int:design_id}", response={200: DesignSchema, 400: ErrorResponseSchema, **E404})
def update_design(request: HttpRequest, design_id: int, data: DesignUpdateSchema):
    design = _get_design(design_id)
    if data.name is not None:
        design.name = data.name.strip()
    for key, value in ticket_service.validate_design(data.dict()).items():
        setattr(design, key, value)
    if data.is_default:
        design.is_default = True  # save() demotes the others
    design.save()
    return design


@ticket_api.post("/designs/{int:design_id}/duplicate", response={200: DesignSchema, **E404})
def duplicate_design(request: HttpRequest, design_id: int):
    src = _get_design(design_id)
    return TicketDesign.objects.create(name=f"{src.name} copy", **{k: getattr(src, k) for k in DESIGN_FIELDS})


@ticket_api.delete("/designs/{int:design_id}", response={200: MessageResponseSchema, 400: ErrorResponseSchema, **E404})
def delete_design(request: HttpRequest, design_id: int):
    design = _get_design(design_id)
    if TicketDesign.objects.count() <= 1:
        raise ValidationError("Can't delete the only ticket design", error_code="LAST_DESIGN")
    design.delete()
    if design.is_default:
        TicketDesign.get_default()
    return {"message": "Ticket design deleted"}


@ticket_api.get("/programmes/{int:programme_id}/design", response={200: ProgrammeDesignSchema, **E404})
def get_programme_design(request: HttpRequest, programme_id: int):
    return {"design_id": _get_programme(programme_id).ticket_design_id}


@ticket_api.post("/programmes/{int:programme_id}/design", response={200: MessageResponseSchema, **E404})
def set_programme_design(request: HttpRequest, programme_id: int, data: ProgrammeDesignSchema):
    programme = _get_programme(programme_id)
    programme.ticket_design = None if data.design_id is None else _get_design(data.design_id)
    programme.save(update_fields=["ticket_design"])
    return {"message": "Ticket design updated"}
