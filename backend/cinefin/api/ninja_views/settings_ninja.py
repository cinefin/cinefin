import logging
import os
import re

from django.conf import settings as django_settings
from django.http import HttpRequest
from ninja import Field, File, Router, Schema, Status, UploadedFile

from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Bumper, Settings
from cinefin.api.mpv_service import mpv_service
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import config_check_service
from cinefin.api.utils import branding
from cinefin.api.utils.assets import system_ident_stream_url

logger = logging.getLogger(__name__)


class BumperSchema(Schema):
    id: int = Field(description="Bumper unique identifier")
    title: str = Field(description="Bumper title")
    duration: float = Field(description="Bumper duration in seconds")


class CinemaIdentSchema(Schema):
    id: int = Field(description="Cinema ident unique identifier")
    title: str = Field(description="Cinema ident title")


class SettingsDataSchema(Schema):
    cinema_name: str = Field(description="Name of the cinema")
    default_cinema_ident_id: int | None = Field(default=None, description="Default cinema ident bumper ID")
    ratings_system: str = Field(default="BBFC", description="Ratings classification system: BBFC or MPAA")

    ticket_total_rows: int = Field(description="Number of seat rows")
    ticket_seats_per_row: int = Field(description="Seats per row")
    ticket_printer_type: str = Field(default="file", description="Printer connection: file or network")
    ticket_printer_device: str = Field(description="Thermal printer device file path")
    ticket_printer_host: str = Field(default="", description="Network printer host (ESC/POS over TCP)")
    ticket_printer_port: int = Field(default=9100, description="Network printer port")
    ticket_printer_timeout: int = Field(default=30, description="Network print socket timeout (seconds)")
    ticket_feed_lines: int = Field(default=2, description="Blank lines fed after each ticket (0-20)")
    ticket_image_mode: str = Field(default="raster", description="Image encoding: raster / column / graphics / off")
    ticket_qr_fun_links: list[str] = Field(
        default_factory=list, description="Link pool for a fun-mode QR element (random pick per ticket)"
    )
    ticket_paper_width: int = Field(default=384, description="Printable width in dots: 384 (58mm) or 576 (80mm)")
    ticket_date_format: str = Field(default="%d/%m/%Y", description="Date format (preset strftime)")
    ticket_time_format: str = Field(default="%H:%M", description="Time format (preset strftime)")

    subtitle_font_size: int = Field(default=55, description="Subtitle font size (mpv sub-font-size)")
    subtitle_color: str = Field(default="#FFFFFF", description="Subtitle text colour #rrggbb")
    subtitle_border_style: str = Field(
        default="outline-and-shadow", description="outline-and-shadow | opaque-box | background-box"
    )
    subtitle_back_color: str = Field(default="#000000", description="Box/shadow colour #rrggbb")
    subtitle_position: int = Field(default=100, description="Vertical position 0 (top) – 100 (bottom)")
    subtitle_margin_y: int = Field(default=22, description="Bottom/top margin (sub-margin-y)")
    subtitle_use_margins: bool = Field(default=True, description="Keep subtitles inside the video margins")
    subtitle_bold: bool = Field(default=False, description="Bold subtitle text")
    playout_server_url: str = Field(
        default="", description="Base URL the playout host uses to fetch streamed media from Cinefin"
    )

    preshow_commands: list[int] = Field(
        default_factory=list, description="Command IDs run before a scheduled programme plays"
    )

    cinema_web_logo_url: str | None = Field(default=None, description="Navbar logo URL (None = default mark)")
    accent_color: str | None = Field(default=None, description="UI accent colour #rrggbb (None = built-in theme)")
    display_time_format: str = Field(default="24h", description="Wall-clock rendering across the UI: 24h or 12h")

    # Kiosk display defaults (URL parameters override per screen)
    kiosk_layout: str = Field(
        default="wall",
        description="Base layout: wall, spotlight, split, board, tonight or auto",
    )
    kiosk_rotate_minutes: int = Field(default=0, description="Cycle base layouts every N minutes (0 = off)")
    kiosk_header: bool = Field(default=True, description="Show the cinema name/logo header")
    kiosk_clock: bool = Field(default=True, description="Show the clock")
    kiosk_takeover: bool = Field(default=True, description="Now Showing takeover while a programme is live")
    kiosk_countdown_minutes: int = Field(default=30, description="Countdown engage threshold in minutes (0 = off)")
    kiosk_night: bool = Field(default=False, description="Dim to a clock during quiet hours")
    kiosk_night_start: str = Field(default="01:00", description="Night hours start (HH:MM)")
    kiosk_night_end: str = Field(default="08:00", description="Night hours end (HH:MM)")
    kiosk_content_source: str = Field(default="flagged", description="Films shown: flagged, all or scheduled")
    kiosk_show_showtimes: bool = Field(default=True, description="Show next showtimes on poster-wall tiles")

    telemetry_enabled: bool = Field(default=False, description="Opt-in anonymous daily telemetry heartbeat")
    telemetry_host: str = Field(default="", description="Aptabase host (blank = disabled)")
    telemetry_app_key: str = Field(default="", description="Aptabase App-Key")
    telemetry_install_id: str = Field(default="", description="Anonymous install id (read-only, blank until opt-in)")

    updated_at: str = Field(description="Last update timestamp")
    default_cinema_ident: CinemaIdentSchema | None = Field(default=None, description="Default cinema ident details")


class GetSettingsDataSchema(Schema):
    settings: SettingsDataSchema = Field(description="Cinema settings")
    bumpers: list[BumperSchema] = Field(description="Available bumpers for cinema idents")


class GetSettingsResponseSchema(SuccessResponseSchema):
    data: GetSettingsDataSchema


class UpdateSettingsSchema(Schema):
    cinema_name: str | None = Field(default=None, description="Cinema name")
    default_cinema_ident: int | None = Field(default=None, description="Default cinema ident bumper ID")

    ticket_total_rows: int | None = Field(default=None, ge=1, le=26, description="Total seat rows")
    ticket_seats_per_row: int | None = Field(default=None, ge=1, le=100, description="Seats per row")
    ticket_printer_type: str | None = Field(default=None, description="Printer connection: file or network")
    ticket_printer_device: str | None = Field(default=None, description="Thermal printer device file path")
    ticket_printer_host: str | None = Field(default=None, description="Network printer host")
    ticket_printer_port: int | None = Field(default=None, ge=1, le=65535, description="Network printer port")
    ticket_printer_timeout: int | None = Field(
        default=None, ge=1, le=600, description="Network print socket timeout (seconds)"
    )
    ticket_feed_lines: int | None = Field(default=None, ge=0, le=20, description="Blank lines fed after each ticket")
    ticket_image_mode: str | None = Field(default=None, description="Image encoding: raster / column / graphics / off")
    ticket_qr_fun_links: list[str] | None = Field(
        default=None, description="Link pool for a fun-mode QR element (empty list = no QR)"
    )
    ticket_paper_width: int | None = Field(
        default=None, description="Printable width in dots: 384 (58mm) or 576 (80mm)"
    )
    ticket_date_format: str | None = Field(default=None, description="Date format (preset strftime)")
    ticket_time_format: str | None = Field(default=None, description="Time format (preset strftime)")

    subtitle_font_size: int | None = Field(default=None, ge=8, le=200, description="Subtitle font size")
    subtitle_color: str | None = Field(default=None, description="Subtitle text colour #rrggbb")
    subtitle_border_style: str | None = Field(
        default=None, description="outline-and-shadow | opaque-box | background-box"
    )
    subtitle_back_color: str | None = Field(default=None, description="Box/shadow colour #rrggbb")
    subtitle_position: int | None = Field(default=None, ge=0, le=100, description="Vertical position 0–100")
    subtitle_margin_y: int | None = Field(default=None, ge=0, le=300, description="Bottom/top margin")
    subtitle_use_margins: bool | None = Field(default=None, description="Keep subtitles inside the video margins")
    subtitle_bold: bool | None = Field(default=None, description="Bold subtitle text")
    playout_server_url: str | None = Field(
        default=None, description="Base URL the playout host uses to fetch streamed media from Cinefin"
    )

    preshow_commands: list[int] | None = Field(
        default=None, description="Command IDs run before a scheduled programme plays"
    )

    ratings_system: str | None = Field(default=None, description="Ratings classification system: BBFC or MPAA")

    accent_color: str | None = Field(
        default=None, description="UI accent colour #rrggbb; empty string resets to the built-in theme"
    )
    display_time_format: str | None = Field(default=None, description="Wall-clock rendering: 24h or 12h")

    kiosk_layout: str | None = Field(
        default=None,
        description="Base layout: wall, spotlight, split, board, tonight, auto",
    )
    kiosk_rotate_minutes: int | None = Field(default=None, ge=0, le=180, description="Layout rotation (0 = off)")
    kiosk_header: bool | None = Field(default=None, description="Show the cinema name/logo header")
    kiosk_clock: bool | None = Field(default=None, description="Show the clock")
    kiosk_takeover: bool | None = Field(default=None, description="Now Showing takeover on/off")
    kiosk_countdown_minutes: int | None = Field(default=None, ge=0, le=480, description="Countdown threshold")
    kiosk_night: bool | None = Field(default=None, description="Night hours on/off")
    kiosk_night_start: str | None = Field(default=None, description="Night hours start (HH:MM)")
    kiosk_night_end: str | None = Field(default=None, description="Night hours end (HH:MM)")
    kiosk_content_source: str | None = Field(default=None, description="Films shown: flagged, all or scheduled")
    kiosk_show_showtimes: bool | None = Field(default=None, description="Showtimes on poster-wall tiles")

    telemetry_enabled: bool | None = Field(default=None, description="Opt-in anonymous daily telemetry heartbeat")
    telemetry_host: str | None = Field(default=None, description="Aptabase host (blank = disabled)")
    telemetry_app_key: str | None = Field(default=None, description="Aptabase App-Key")


class TestIdentSchema(Schema):
    bumper_id: int | None = Field(
        default=None,
        description="User media item to test as the ident; omit to test the bundled System Ident",
    )


# Configuration checks are non-destructive; a failed check is a result, not an error, so they all answer 200.


class TmdbTestInput(Schema):
    api_key: str | None = Field(default=None, description="Key to test (blank = the saved key)")


class RatingsTestInput(Schema):
    system: str | None = Field(default=None, description="Ratings system to probe (blank = the configured one)")


class PrinterTestInput(Schema):
    printer_type: str | None = Field(default=None, description="file / network (blank = the saved type)")
    device: str | None = Field(default=None, description="Device file path, for file mode")
    host: str | None = Field(default=None, description="Printer host, for network mode")
    port: int | None = Field(default=None, ge=1, le=65535, description="Printer port, for network mode")


class CheckResultResponse(Schema):
    success: bool = True
    ok: bool = Field(description="Whether the test passed")
    message: str = Field(description="Human-readable result")


settings_api = Router()


def _build_settings_response(all_settings: dict, updated_at: str) -> SettingsDataSchema:
    subtitles = all_settings.get("playout", {}).get("subtitles", {})
    default_ident_id = all_settings.get("cinema", {}).get("default_ident_id")
    default_ident = None
    if default_ident_id:
        try:
            bumper = Bumper.objects.get(id=default_ident_id)
            default_ident = CinemaIdentSchema(id=bumper.id, title=bumper.title)
        except Bumper.DoesNotExist:
            pass

    return SettingsDataSchema(
        cinema_name=all_settings.get("cinema", {}).get("name", "Cinefin"),
        default_cinema_ident_id=default_ident_id,
        ratings_system=all_settings.get("cinema", {}).get("ratings_system", "BBFC"),
        ticket_total_rows=all_settings.get("tickets", {}).get("total_rows", 10),
        ticket_seats_per_row=all_settings.get("tickets", {}).get("seats_per_row", 20),
        ticket_printer_type=all_settings.get("tickets", {}).get("printer_type", "file"),
        ticket_printer_device=all_settings.get("tickets", {}).get("printer_device", "/dev/usb/lp0"),
        ticket_printer_host=all_settings.get("tickets", {}).get("printer_host", ""),
        ticket_printer_port=all_settings.get("tickets", {}).get("printer_port", 9100),
        ticket_printer_timeout=all_settings.get("tickets", {}).get("printer_timeout", 30),
        ticket_feed_lines=all_settings.get("tickets", {}).get("feed_lines", 2),
        ticket_image_mode=all_settings.get("tickets", {}).get("image_mode", "raster"),
        ticket_qr_fun_links=[
            link for link in all_settings.get("tickets", {}).get("qr_fun_links", []) if isinstance(link, str)
        ],
        ticket_paper_width=all_settings.get("tickets", {}).get("paper_width", 384),
        ticket_date_format=all_settings.get("tickets", {}).get("date_format", "%d/%m/%Y"),
        ticket_time_format=all_settings.get("tickets", {}).get("time_format", "%H:%M"),
        subtitle_font_size=int(subtitles.get("font_size", 55)),
        subtitle_color=subtitles.get("color", "#FFFFFF"),
        subtitle_border_style=subtitles.get("border_style", "outline-and-shadow"),
        subtitle_back_color=subtitles.get("back_color", "#000000"),
        subtitle_position=int(subtitles.get("position", 100)),
        subtitle_margin_y=int(subtitles.get("margin_y", 22)),
        subtitle_use_margins=bool(subtitles.get("use_margins", True)),
        subtitle_bold=bool(subtitles.get("bold", False)),
        playout_server_url=all_settings.get("playout", {}).get("server_url", ""),
        preshow_commands=all_settings.get("scheduler", {}).get("preshow_commands", []),
        cinema_web_logo_url=branding.web_logo_url(all_settings.get("cinema", {}).get("web_logo_path")),
        accent_color=branding.valid_accent_color(all_settings.get("display", {}).get("accent_color")),
        display_time_format=("12h" if all_settings.get("display", {}).get("time_format") == "12h" else "24h"),
        kiosk_layout=all_settings.get("kiosk", {}).get("layout", "wall"),
        kiosk_rotate_minutes=all_settings.get("kiosk", {}).get("rotate_minutes", 0),
        kiosk_header=bool(all_settings.get("kiosk", {}).get("header", True)),
        kiosk_clock=bool(all_settings.get("kiosk", {}).get("clock", True)),
        kiosk_takeover=bool(all_settings.get("kiosk", {}).get("takeover", True)),
        kiosk_countdown_minutes=all_settings.get("kiosk", {}).get("countdown_minutes", 30),
        kiosk_night=bool(all_settings.get("kiosk", {}).get("night", False)),
        kiosk_night_start=all_settings.get("kiosk", {}).get("night_start", "01:00"),
        kiosk_night_end=all_settings.get("kiosk", {}).get("night_end", "08:00"),
        kiosk_content_source=all_settings.get("kiosk", {}).get("content_source", "flagged"),
        kiosk_show_showtimes=bool(all_settings.get("kiosk", {}).get("show_showtimes", True)),
        telemetry_enabled=bool(all_settings.get("telemetry", {}).get("enabled", False)),
        telemetry_host=all_settings.get("telemetry", {}).get("host", ""),
        telemetry_app_key=all_settings.get("telemetry", {}).get("app_key", ""),
        telemetry_install_id=all_settings.get("telemetry", {}).get("install_id", ""),
        updated_at=updated_at,
        default_cinema_ident=default_ident,
    )


@settings_api.get("/", response={200: GetSettingsResponseSchema, 500: ErrorResponseSchema})
def get_settings(request: HttpRequest):
    all_settings = Settings.get_all()
    instance = Settings._get_instance()

    bumpers = Bumper.objects.all().values("id", "title", "duration")

    settings_data = _build_settings_response(all_settings, instance.updated_at.isoformat())
    bumper_list = [BumperSchema(**bumper) for bumper in bumpers]

    return Status(
        200,
        GetSettingsResponseSchema(
            message="Settings retrieved successfully",
            data=GetSettingsDataSchema(settings=settings_data, bumpers=bumper_list),
        ),
    )


@settings_api.post(
    "/",
    response={200: MessageResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def update_settings(request: HttpRequest, data: UpdateSettingsSchema):
    # Map flat field names to nested settings keys
    field_mapping = {
        "cinema_name": "cinema.name",
        "default_cinema_ident": "cinema.default_ident_id",
        "ratings_system": "cinema.ratings_system",
        "ticket_total_rows": "tickets.total_rows",
        "ticket_seats_per_row": "tickets.seats_per_row",
        "ticket_printer_type": "tickets.printer_type",
        "ticket_printer_device": "tickets.printer_device",
        "ticket_printer_host": "tickets.printer_host",
        "ticket_printer_port": "tickets.printer_port",
        "ticket_printer_timeout": "tickets.printer_timeout",
        "ticket_feed_lines": "tickets.feed_lines",
        "ticket_image_mode": "tickets.image_mode",
        "ticket_qr_fun_links": "tickets.qr_fun_links",
        "ticket_paper_width": "tickets.paper_width",
        "ticket_date_format": "tickets.date_format",
        "ticket_time_format": "tickets.time_format",
        "subtitle_font_size": "playout.subtitles.font_size",
        "subtitle_color": "playout.subtitles.color",
        "subtitle_border_style": "playout.subtitles.border_style",
        "subtitle_back_color": "playout.subtitles.back_color",
        "subtitle_position": "playout.subtitles.position",
        "subtitle_margin_y": "playout.subtitles.margin_y",
        "subtitle_use_margins": "playout.subtitles.use_margins",
        "subtitle_bold": "playout.subtitles.bold",
        "playout_server_url": "playout.server_url",
        "preshow_commands": "scheduler.preshow_commands",
        "accent_color": "display.accent_color",
        "display_time_format": "display.time_format",
        "kiosk_layout": "kiosk.layout",
        "kiosk_rotate_minutes": "kiosk.rotate_minutes",
        "kiosk_header": "kiosk.header",
        "kiosk_clock": "kiosk.clock",
        "kiosk_takeover": "kiosk.takeover",
        "kiosk_countdown_minutes": "kiosk.countdown_minutes",
        "kiosk_night": "kiosk.night",
        "kiosk_night_start": "kiosk.night_start",
        "kiosk_night_end": "kiosk.night_end",
        "kiosk_content_source": "kiosk.content_source",
        "kiosk_show_showtimes": "kiosk.show_showtimes",
        "telemetry_enabled": "telemetry.enabled",
        "telemetry_host": "telemetry.host",
        "telemetry_app_key": "telemetry.app_key",
    }

    # Each failure carries the offending field in details.field so the UI can highlight it.
    if data.ratings_system is not None and data.ratings_system not in ("BBFC", "MPAA"):
        raise ValidationError("Ratings system must be BBFC or MPAA", details={"field": "ratings_system"})

    if data.ticket_printer_type is not None and data.ticket_printer_type not in ("file", "network"):
        raise ValidationError("Printer connection must be file or network", details={"field": "ticket_printer_type"})

    if data.ticket_image_mode is not None and data.ticket_image_mode not in ("raster", "column", "graphics", "off"):
        raise ValidationError(
            "Image mode must be raster, column, graphics or off", details={"field": "ticket_image_mode"}
        )

    if data.ticket_paper_width is not None and data.ticket_paper_width not in (384, 576):
        raise ValidationError("Paper width must be 384 or 576 dots", details={"field": "ticket_paper_width"})

    # Empty string means "reset" — None can't travel (None fields are skipped as not-provided).
    if data.accent_color is not None and data.accent_color != "":
        if branding.valid_accent_color(data.accent_color) is None:
            raise ValidationError("Accent colour must be a #rrggbb hex value", details={"field": "accent_color"})

    if data.display_time_format is not None and data.display_time_format not in ("24h", "12h"):
        raise ValidationError("Time format must be 24h or 12h", details={"field": "display_time_format"})

    if data.subtitle_border_style is not None and data.subtitle_border_style not in (
        "outline-and-shadow",
        "opaque-box",
        "background-box",
    ):
        raise ValidationError(
            "Subtitle border style must be outline-and-shadow, opaque-box or background-box",
            details={"field": "subtitle_border_style"},
        )
    for _field in ("subtitle_color", "subtitle_back_color"):
        _val = getattr(data, _field)
        if _val is not None and not re.match(r"^#[0-9a-fA-F]{6}$", _val):
            raise ValidationError("Colour must be a #rrggbb hex value", details={"field": _field})

    if data.playout_server_url is not None and data.playout_server_url.strip():
        if not re.match(r"^https?://", data.playout_server_url.strip()):
            raise ValidationError(
                "Streaming base URL must start with http:// or https://",
                details={"field": "playout_server_url"},
            )

    if data.telemetry_host is not None and data.telemetry_host.strip():
        if not re.match(r"^https?://", data.telemetry_host.strip()):
            raise ValidationError(
                "Telemetry host must start with http:// or https://",
                details={"field": "telemetry_host"},
            )

    kiosk_choices = {
        "kiosk_layout": ("wall", "spotlight", "split", "board", "tonight", "auto"),
        "kiosk_content_source": ("flagged", "all", "scheduled"),
    }
    for field_name, choices in kiosk_choices.items():
        value = getattr(data, field_name)
        if value is not None and value not in choices:
            raise ValidationError(
                f"Must be one of: {', '.join(str(c) for c in choices)}", details={"field": field_name}
            )
    for field_name in ("kiosk_night_start", "kiosk_night_end"):
        value = getattr(data, field_name)
        if value is not None and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
            raise ValidationError("Must be a time like 01:00", details={"field": field_name})

    if data.default_cinema_ident is not None and data.default_cinema_ident:
        try:
            Bumper.objects.get(id=data.default_cinema_ident)
        except Bumper.DoesNotExist:
            raise NotFoundError("Selected cinema ident not found", details={"field": "default_cinema_ident"}) from None

    # A ratings-system change re-points denormalised scalar certificates; note the
    # ident + streaming URL (which drive the host's idle screen) to detect changes.
    previous_ratings_system = Settings.get_ratings_system()
    previous_ident_id = Settings.get("cinema.default_ident_id")
    previous_server_url = Settings.get("playout.server_url")

    for field_name, settings_key in field_mapping.items():
        value = getattr(data, field_name, None)
        if value is None:
            continue
        if field_name == "accent_color":
            value = branding.valid_accent_color(value)  # "" -> None (reset)
            Settings.set(settings_key, value)
            continue
        if field_name == "preshow_commands":
            from cinefin.api.models import Command

            valid = set(Command.objects.filter(id__in=value).values_list("id", flat=True))
            seen, cleaned = set(), []
            for cid in value:
                if cid in valid and cid not in seen:
                    seen.add(cid)
                    cleaned.append(cid)
            value = cleaned
        Settings.set(settings_key, value)

    # Mint the anonymous install id the first time telemetry is switched on.
    if data.telemetry_enabled:
        from cinefin.api.services import telemetry_service

        telemetry_service.ensure_install_id()

    if data.ratings_system and data.ratings_system != previous_ratings_system:
        from cinefin.api.ratings.service import denormalize_certificates

        denormalize_certificates(data.ratings_system)

    # Apply subtitle style live (best-effort: a disconnected player must not fail the save).
    if any(getattr(data, field_name) is not None for field_name in field_mapping if field_name.startswith("subtitle_")):
        try:
            mpv_service.apply_subtitle_style()
        except Exception:  # noqa: BLE001 — a live-apply failure is not a save failure
            logger.debug("Could not apply subtitle style live", exc_info=True)

    # If the ident or streaming URL changed, re-push the host's streamed idle
    # screen (best-effort; applies on the next player restart).
    ident_changed = (
        data.default_cinema_ident is not None and Settings.get("cinema.default_ident_id") != previous_ident_id
    )
    server_url_changed = (
        data.playout_server_url is not None and Settings.get("playout.server_url") != previous_server_url
    )
    if ident_changed or server_url_changed:
        try:
            from cinefin.api.services.playout_agent_service import playout_agent_service

            playout_agent_service.resync_idle_media()
        except Exception:  # noqa: BLE001 — agent sync must not fail the settings save
            logger.debug("Could not resync playout idle media", exc_info=True)

    return Status(200, MessageResponseSchema(message="Settings updated successfully"))


@settings_api.post(
    "/test-ident/",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def test_ident(request: HttpRequest, data: TestIdentSchema):
    """Play the ident — the chosen user media item, or the bundled System Ident when no bumper_id is given."""
    if data.bumper_id is None:
        stream_url, label = system_ident_stream_url(), "System Ident"
    else:
        try:
            bumper = Bumper.objects.get(id=data.bumper_id)
        except Bumper.DoesNotExist:
            raise NotFoundError("User media item not found") from None
        # Streaming-only: play the stream URL; the local file_path means nothing on a remote host.
        stream_url = (bumper.get_stream_url() or {}).get("stream_url")
        if not stream_url:
            raise UnprocessableEntityError("That user media item has no stream URL")
        label = bumper.title

    if mpv_service is None:
        raise UnprocessableEntityError("No MPV service available")

    success = mpv_service.load_file(stream_url, replace=True)
    if not success:
        raise UnprocessableEntityError("Failed to load the ident")

    mpv_service.play()

    return Status(200, MessageResponseSchema(message=f"Playing ident: {label}"))


@settings_api.post("/test-tmdb/", response=CheckResultResponse)
def test_tmdb(request: HttpRequest, data: TmdbTestInput):
    """Verify a TMDB API key with a cheap authenticated call (blank = the saved one; invalid is ok=false, not an error)."""
    result = config_check_service.test_tmdb_key(data.api_key)
    return Status(200, CheckResultResponse(**result))


@settings_api.post("/test-ratings/", response=CheckResultResponse)
def test_ratings(request: HttpRequest, data: RatingsTestInput):
    """Probe the certificate-rating provider for reachability (blank = the configured one; unreachable is ok=false)."""
    result = config_check_service.test_ratings_provider(data.system)
    return Status(200, CheckResultResponse(**result))


@settings_api.post("/test-printer/", response=CheckResultResponse)
def test_printer(request: HttpRequest, data: PrinterTestInput):
    """Check the ticket printer without printing (file: path writable; network: short TCP connect); blanks fall back to saved settings."""
    result = config_check_service.test_printer(
        printer_type=data.printer_type, device=data.device, host=data.host, port=data.port
    )
    return Status(200, CheckResultResponse(**result))


@settings_api.post("/reset/", response={200: MessageResponseSchema, 500: ErrorResponseSchema})
def reset_settings(request: HttpRequest):
    Settings.reset()

    return Status(200, MessageResponseSchema(message="Settings reset to defaults"))


# Web branding logo (navbar) — distinct from the printed ticket logo.
class BrandingLogoDataSchema(Schema):
    logo_url: str | None = Field(default=None, description="Web URL of the stored logo (None after delete)")


class BrandingLogoResponseSchema(SuccessResponseSchema):
    data: BrandingLogoDataSchema = Field(..., description="Branding logo state")


@settings_api.post(
    "/branding/logo",
    response={200: BrandingLogoResponseSchema, 400: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def upload_branding_logo(request: HttpRequest, logo: UploadedFile = File(...)):
    """Upload the web UI (navbar) logo. PNG, JPG or GIF, max 2 MB."""
    allowed_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif"}
    if logo.content_type not in allowed_types:
        raise ValidationError(
            "Invalid file type. Please upload a PNG, JPG or GIF image", error_code="INVALID_FILE_TYPE"
        )
    if logo.size > 2 * 1024 * 1024:
        raise ValidationError("File too large. Maximum size is 2MB", error_code="FILE_TOO_LARGE")

    try:
        logo_dir = os.path.join(django_settings.MEDIA_ROOT, branding.WEB_LOGO_SUBDIR)
        os.makedirs(logo_dir, exist_ok=True)

        old_abs = branding.web_logo_abs_path(Settings.get("cinema.web_logo_path"))
        if old_abs and os.path.exists(old_abs):
            os.remove(old_abs)

        from django.utils import timezone as dj_tz

        filename = f"logo_{dj_tz.now().strftime('%Y%m%d_%H%M%S')}{allowed_types[logo.content_type]}"
        rel_path = os.path.join(branding.WEB_LOGO_SUBDIR, filename)
        with open(os.path.join(django_settings.MEDIA_ROOT, rel_path), "wb") as f:
            for chunk in logo.chunks():
                f.write(chunk)

        Settings.set("cinema.web_logo_path", rel_path)
        return Status(
            200,
            BrandingLogoResponseSchema(
                message="Logo uploaded",
                data=BrandingLogoDataSchema(logo_url=branding.web_logo_url(rel_path)),
            ),
        )
    except PermissionError as e:
        logger.exception("Branding logo upload failed")
        raise UnprocessableEntityError(
            f"Cannot write to the media directory ({e}). Check ownership of "
            f"{django_settings.MEDIA_ROOT} — fix with e.g. 'sudo chown -R <app-user> {django_settings.MEDIA_ROOT}'.",
            error_code="LOGO_UPLOAD_FAILED",
        ) from e
    except Exception as e:
        logger.exception("Branding logo upload failed")
        raise UnprocessableEntityError(f"Error uploading logo: {e}", error_code="LOGO_UPLOAD_FAILED") from e


@settings_api.delete("/branding/logo", response={200: BrandingLogoResponseSchema, 500: ErrorResponseSchema})
def delete_branding_logo(request: HttpRequest):
    """Remove the web UI logo and return the navbar to the default mark."""
    old_abs = branding.web_logo_abs_path(Settings.get("cinema.web_logo_path"))
    if old_abs and os.path.exists(old_abs):
        try:
            os.remove(old_abs)
        except OSError:
            logger.warning("Could not delete branding logo file %s", old_abs)
    Settings.set("cinema.web_logo_path", None)
    return Status(200, BrandingLogoResponseSchema(message="Logo removed", data=BrandingLogoDataSchema(logo_url=None)))
