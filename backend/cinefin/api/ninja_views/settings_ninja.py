import logging
import os
import re

from django.conf import settings as django_settings
from django.http import HttpRequest
from ninja import Field, File, Router, Schema, Status, UploadedFile

from cinefin.api.exceptions import ConflictError, NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Bumper, Settings
from cinefin.api.mpv_service import mpv_service
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import config_check_service, standby
from cinefin.api.utils import branding

logger = logging.getLogger(__name__)


class BumperSchema(Schema):
    id: int
    title: str
    duration: float
    hold_point: float | None = Field(None, description="As the ident: where standby freezes (null = last frame)")


class CinemaIdentSchema(Schema):
    id: int
    title: str


class SettingsDataSchema(Schema):
    cinema_name: str
    default_cinema_ident_id: int | None = Field(
        default=None, description="Default cinema ident media item ID (null = the System Ident)"
    )
    ratings_system: str = Field(default="BBFC", description="Ratings classification system: BBFC or MPAA")

    ticket_total_rows: int
    ticket_seats_per_row: int
    ticket_printer_type: str = Field(default="file", description="Printer connection: file or network")
    ticket_printer_device: str
    ticket_printer_host: str = Field(default="", description="Network printer host (ESC/POS over TCP)")
    ticket_printer_port: int = 9100
    ticket_printer_timeout: int = Field(default=30, description="Network print socket timeout (seconds)")
    ticket_feed_lines: int = Field(default=2, description="Blank lines fed after each ticket (0-20)")
    ticket_cut: str = Field(default="off", description="Paper cut after each ticket: off / partial / full")
    ticket_image_mode: str = Field(default="raster", description="Image encoding: raster / column / graphics / off")
    ticket_paper_width: int = Field(default=384, description="Printable width in dots: 384 (58mm) or 576 (80mm)")

    subtitle_font_size: int = Field(default=55, description="Subtitle font size (mpv sub-font-size)")
    subtitle_color: str = "#FFFFFF"
    subtitle_border_style: str = Field(
        default="outline-and-shadow", description="outline-and-shadow | opaque-box | background-box"
    )
    subtitle_back_color: str = Field(default="#000000", description="Box/shadow colour #rrggbb")
    subtitle_position: int = Field(default=100, description="Vertical position 0 (top) – 100 (bottom)")
    subtitle_margin_y: int = Field(default=22, description="Bottom/top margin (sub-margin-y)")
    subtitle_use_margins: bool = True
    subtitle_bold: bool = False
    playout_server_url: str = Field(
        default="", description="Base URL the playout host uses to fetch streamed media from Cinefin"
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
    kiosk_clock: bool = True
    kiosk_takeover: bool = True
    kiosk_countdown_minutes: int = Field(default=30, description="Countdown engage threshold in minutes (0 = off)")
    kiosk_night: bool = False
    kiosk_night_start: str = Field(default="01:00", description="Night hours start (HH:MM)")
    kiosk_night_end: str = Field(default="08:00", description="Night hours end (HH:MM)")
    kiosk_content_source: str = Field(default="flagged", description="Films shown: flagged, all or scheduled")
    kiosk_show_showtimes: bool = Field(default=True, description="Show next showtimes on poster-wall tiles")

    updated_at: str
    default_cinema_ident: CinemaIdentSchema | None = None


class GetSettingsDataSchema(Schema):
    settings: SettingsDataSchema
    bumpers: list[BumperSchema]


class GetSettingsResponseSchema(SuccessResponseSchema):
    data: GetSettingsDataSchema


class UpdateSettingsSchema(Schema):
    cinema_name: str | None = None
    default_cinema_ident: int | None = Field(
        default=None, description="Default cinema ident media item ID; an explicit null selects the System Ident"
    )

    ticket_total_rows: int | None = Field(default=None, ge=1, le=26)
    ticket_seats_per_row: int | None = Field(default=None, ge=1, le=100)
    ticket_printer_type: str | None = Field(default=None, description="Printer connection: file or network")
    ticket_printer_device: str | None = None
    ticket_printer_host: str | None = None
    ticket_printer_port: int | None = Field(default=None, ge=1, le=65535)
    ticket_printer_timeout: int | None = Field(
        default=None, ge=1, le=600, description="Network print socket timeout (seconds)"
    )
    ticket_feed_lines: int | None = Field(default=None, ge=0, le=20)
    ticket_cut: str | None = Field(default=None, description="Paper cut after each ticket: off / partial / full")
    ticket_image_mode: str | None = Field(default=None, description="Image encoding: raster / column / graphics / off")
    ticket_paper_width: int | None = Field(
        default=None, description="Printable width in dots: 384 (58mm) or 576 (80mm)"
    )

    subtitle_font_size: int | None = Field(default=None, ge=8, le=200)
    subtitle_color: str | None = None
    subtitle_border_style: str | None = Field(
        default=None, description="outline-and-shadow | opaque-box | background-box"
    )
    subtitle_back_color: str | None = Field(default=None, description="Box/shadow colour #rrggbb")
    subtitle_position: int | None = Field(default=None, ge=0, le=100, description="Vertical position 0–100")
    subtitle_margin_y: int | None = Field(default=None, ge=0, le=300, description="Bottom/top margin")
    subtitle_use_margins: bool | None = None
    subtitle_bold: bool | None = None
    playout_server_url: str | None = Field(
        default=None, description="Base URL the playout host uses to fetch streamed media from Cinefin"
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
    kiosk_clock: bool | None = None
    kiosk_takeover: bool | None = Field(default=None, description="Now Showing takeover on/off")
    kiosk_countdown_minutes: int | None = Field(default=None, ge=0, le=480)
    kiosk_night: bool | None = Field(default=None, description="Night hours on/off")
    kiosk_night_start: str | None = Field(default=None, description="Night hours start (HH:MM)")
    kiosk_night_end: str | None = Field(default=None, description="Night hours end (HH:MM)")
    kiosk_content_source: str | None = Field(default=None, description="Films shown: flagged, all or scheduled")
    kiosk_show_showtimes: bool | None = Field(default=None, description="Showtimes on poster-wall tiles")


# Configuration checks are non-destructive; a failed check is a result, not an error, so they all answer 200.


class TmdbTestInput(Schema):
    api_key: str | None = Field(default=None, description="Key to test (blank = the saved key)")


class PrinterTestInput(Schema):
    printer_type: str | None = Field(default=None, description="file / network (blank = the saved type)")
    device: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)


class CheckResultResponse(Schema):
    success: bool = True
    ok: bool
    message: str = Field(description="Human-readable result")


settings_api = Router()


# Flat API field -> (dotted Settings key, default when unset, cast applied on read).
_FIELDS = {
    "cinema_name": ("cinema.name", "Cinefin", None),
    "ratings_system": ("cinema.ratings_system", "BBFC", None),
    "ticket_total_rows": ("tickets.total_rows", 10, None),
    "ticket_seats_per_row": ("tickets.seats_per_row", 20, None),
    "ticket_printer_type": ("tickets.printer_type", "file", None),
    "ticket_printer_device": ("tickets.printer_device", "/dev/usb/lp0", None),
    "ticket_printer_host": ("tickets.printer_host", "", None),
    "ticket_printer_port": ("tickets.printer_port", 9100, None),
    "ticket_printer_timeout": ("tickets.printer_timeout", 30, None),
    "ticket_feed_lines": ("tickets.feed_lines", 2, None),
    "ticket_cut": ("tickets.cut", "off", None),
    "ticket_image_mode": ("tickets.image_mode", "raster", None),
    "ticket_paper_width": ("tickets.paper_width", 384, None),
    "subtitle_font_size": ("playout.subtitles.font_size", 55, int),
    "subtitle_color": ("playout.subtitles.color", "#FFFFFF", None),
    "subtitle_border_style": ("playout.subtitles.border_style", "outline-and-shadow", None),
    "subtitle_back_color": ("playout.subtitles.back_color", "#000000", None),
    "subtitle_position": ("playout.subtitles.position", 100, int),
    "subtitle_margin_y": ("playout.subtitles.margin_y", 22, int),
    "subtitle_use_margins": ("playout.subtitles.use_margins", True, bool),
    "subtitle_bold": ("playout.subtitles.bold", False, bool),
    "playout_server_url": ("playout.server_url", "", None),
    "kiosk_layout": ("kiosk.layout", "wall", None),
    "kiosk_rotate_minutes": ("kiosk.rotate_minutes", 0, None),
    "kiosk_header": ("kiosk.header", True, bool),
    "kiosk_clock": ("kiosk.clock", True, bool),
    "kiosk_takeover": ("kiosk.takeover", True, bool),
    "kiosk_countdown_minutes": ("kiosk.countdown_minutes", 30, None),
    "kiosk_night": ("kiosk.night", False, bool),
    "kiosk_night_start": ("kiosk.night_start", "01:00", None),
    "kiosk_night_end": ("kiosk.night_end", "08:00", None),
    "kiosk_content_source": ("kiosk.content_source", "flagged", None),
    "kiosk_show_showtimes": ("kiosk.show_showtimes", True, bool),
}

# Fields written on update besides _FIELDS (read back specially).
_WRITE_ONLY = {
    "default_cinema_ident": "cinema.default_ident_id",
    "accent_color": "display.accent_color",
    "display_time_format": "display.time_format",
}

# Each failure carries the offending field in details.field so the UI can highlight it.
_CHOICES = {
    "ratings_system": (("BBFC", "MPAA"), "Ratings system must be BBFC or MPAA"),
    "ticket_printer_type": (("file", "network"), "Printer connection must be file or network"),
    "ticket_image_mode": (
        ("raster", "column", "graphics", "off"),
        "Image mode must be raster, column, graphics or off",
    ),
    "ticket_cut": (("off", "partial", "full"), "Cut must be off, partial or full"),
    "ticket_paper_width": ((384, 576), "Paper width must be 384 or 576 dots"),
    "display_time_format": (("24h", "12h"), "Time format must be 24h or 12h"),
    "subtitle_border_style": (
        ("outline-and-shadow", "opaque-box", "background-box"),
        "Subtitle border style must be outline-and-shadow, opaque-box or background-box",
    ),
    "kiosk_layout": (("wall", "spotlight", "split", "board", "tonight", "auto"), None),
    "kiosk_content_source": (("flagged", "all", "scheduled"), None),
}


def _dig(tree: dict, dotted: str, default):
    *parents, leaf = dotted.split(".")
    for part in parents:
        tree = tree.get(part, {})
    return tree.get(leaf, default)


def _build_settings_response(all_settings: dict, updated_at: str) -> SettingsDataSchema:
    # A saved id whose media item was deleted reads as the System Ident, which is
    # what standby plays for it; echoing the dead id would leave the form holding
    # a choice it cannot show and the save rejecting it as not found.
    saved_ident_id = _dig(all_settings, "cinema.default_ident_id", None)
    bumper = Bumper.objects.filter(id=saved_ident_id).first() if saved_ident_id else None
    values = {}
    for name, (key, default, cast) in _FIELDS.items():
        value = _dig(all_settings, key, default)
        values[name] = cast(value) if cast else value
    return SettingsDataSchema(
        **values,
        default_cinema_ident_id=bumper.id if bumper else None,
        default_cinema_ident=CinemaIdentSchema(id=bumper.id, title=bumper.title) if bumper else None,
        cinema_web_logo_url=branding.web_logo_url(_dig(all_settings, "cinema.web_logo_path", None)),
        accent_color=branding.valid_accent_color(_dig(all_settings, "display.accent_color", None)),
        display_time_format="12h" if _dig(all_settings, "display.time_format", None) == "12h" else "24h",
        updated_at=updated_at,
    )


@settings_api.get("/", response={200: GetSettingsResponseSchema, 500: ErrorResponseSchema})
def get_settings(request: HttpRequest):
    settings_data = _build_settings_response(Settings.get_all(), Settings._get_instance().updated_at.isoformat())
    bumpers = [BumperSchema(**b) for b in Bumper.objects.all().values("id", "title", "duration", "hold_point")]
    return Status(
        200,
        GetSettingsResponseSchema(
            message="Settings retrieved successfully",
            data=GetSettingsDataSchema(settings=settings_data, bumpers=bumpers),
        ),
    )


def _validate_update(data: UpdateSettingsSchema) -> None:
    for name, (choices, message) in _CHOICES.items():
        value = getattr(data, name)
        if value is not None and value not in choices:
            raise ValidationError(
                message or f"Must be one of: {', '.join(str(c) for c in choices)}", details={"field": name}
            )
    # Empty string means "reset" here (a None accent is skipped as not-provided).
    if data.accent_color and branding.valid_accent_color(data.accent_color) is None:
        raise ValidationError("Accent colour must be a #rrggbb hex value", details={"field": "accent_color"})
    for name in ("subtitle_color", "subtitle_back_color"):
        value = getattr(data, name)
        if value is not None and not re.match(r"^#[0-9a-fA-F]{6}$", value):
            raise ValidationError("Colour must be a #rrggbb hex value", details={"field": name})
    if data.playout_server_url and data.playout_server_url.strip():
        if not re.match(r"^https?://", data.playout_server_url.strip()):
            raise ValidationError(
                "Streaming base URL must start with http:// or https://", details={"field": "playout_server_url"}
            )
    for name in ("kiosk_night_start", "kiosk_night_end"):
        value = getattr(data, name)
        if value is not None and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
            raise ValidationError("Must be a time like 01:00", details={"field": name})
    if data.default_cinema_ident is not None and not Bumper.objects.filter(id=data.default_cinema_ident).exists():
        raise NotFoundError("Selected cinema ident not found", details={"field": "default_cinema_ident"})


@settings_api.post(
    "/",
    response={200: MessageResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def update_settings(request: HttpRequest, data: UpdateSettingsSchema):
    _validate_update(data)

    # A ratings-system change re-points denormalised scalar certificates; note
    # what goes into the players' standby spec to detect changes to it.
    previous_ratings_system = Settings.get_ratings_system()
    previous_spec = _standby_settings()

    keys = {name: key for name, (key, _, _) in _FIELDS.items()} | _WRITE_ONLY
    for name, key in keys.items():
        value = getattr(data, name)
        if value is None:
            # An explicit null clears the ident (model_fields_set tells it from an omitted one);
            # every other None is "not provided".
            if name == "default_cinema_ident" and name in data.model_fields_set:
                Settings.set(key, None)
            continue
        Settings.set(key, branding.valid_accent_color(value) if name == "accent_color" else value)  # "" -> reset

    if data.ratings_system and data.ratings_system != previous_ratings_system:
        from cinefin.api.ratings.service import denormalize_certificates

        denormalize_certificates(data.ratings_system)

    # Apply subtitle style live (best-effort: a disconnected player must not fail the save).
    if any(getattr(data, name) is not None for name in _FIELDS if name.startswith("subtitle_")):
        try:
            mpv_service.apply_subtitle_style()
        except Exception:  # noqa: BLE001 — a live-apply failure is not a save failure
            logger.debug("Could not apply subtitle style live", exc_info=True)

    if _standby_settings() != previous_spec:
        standby.push()

    return Status(200, MessageResponseSchema(message="Settings updated successfully"))


def _standby_settings() -> tuple:
    """The settings that go into the players' standby spec (the streaming URL is in the ident's URL)."""
    return (
        Settings.get_cinema_name(),
        Settings.get("cinema.default_ident_id"),
        Settings.get("playout.server_url"),
    )


@settings_api.post(
    "/preview-standby/",
    response={200: MessageResponseSchema, 409: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def preview_standby(request: HttpRequest):
    """Put the player on standby with the saved ident, to see it. Refused while
    a programme or a manual queue is loaded, since standby would end it."""
    if not mpv_service.idle():
        raise ConflictError(
            "A programme or manual queue is loaded; end it before previewing standby", error_code="PLAYER_BUSY"
        )
    if not mpv_service.standby():
        raise UnprocessableEntityError("Could not reach the player", error_code="PLAYER_UNREACHABLE")
    return Status(200, MessageResponseSchema(message="The player is on standby"))


@settings_api.post("/test-tmdb/", response=CheckResultResponse)
def test_tmdb(request: HttpRequest, data: TmdbTestInput):
    """Verify a TMDB API key with a cheap authenticated call (blank = the saved one; invalid is ok=false, not an error)."""
    result = config_check_service.test_tmdb_key(data.api_key)
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
    data: BrandingLogoDataSchema


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
