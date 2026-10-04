"""Kiosk display API — the SPA wall display's single read-only data source."""

from django.http import HttpRequest
from ninja import Field, Router, Schema

from cinefin.api.models import Settings
from cinefin.api.schemas.base import ErrorResponseSchema, SuccessResponseSchema
from cinefin.api.services import kiosk_service
from cinefin.api.utils import branding


class KioskFilmSchema(Schema):
    id: int
    title: str
    year: int | None = None
    cert: str = Field("", description="Certificate for the active ratings system")
    runtime: int = Field(0, description="Minutes")
    genres: list[str] = Field(..., description="Up to three genres")
    synopsis: str = ""
    poster: str | None = Field(None, description="Poster thumbnail URL")
    director: str = ""


class KioskScreeningSchema(Schema):
    id: int = Field(..., description="Schedule ID")
    programme: str = Field(..., description="Programme name")
    programme_id: int
    start: str = Field(..., description="Start time (ISO)")
    end: str = Field(..., description="End time (ISO)")
    runtime: int = Field(..., description="Minutes")
    status: str = Field(..., description="Schedule status (scheduled or running)")
    features: list[KioskFilmSchema] = Field(..., description="Every feature, in running order, de-duplicated")


class KioskDisplaySettingsSchema(Schema):
    between: str = Field("whats_on", description="Between screenings: whats_on, screenings, films or week")
    rotate_seconds: int = Field(15, description="Seconds each screening or film shows when they take turns")
    clock: bool = True
    doors_minutes: int = Field(30, description="Minutes before a screening the Doors open screen shows (0 = off)")
    night: bool = Field(False, description="Dim between screenings during night hours")
    night_start: str = Field("01:00", description="Night hours start (HH:MM)")
    night_end: str = Field("08:00", description="Night hours end (HH:MM)")
    content_source: str = Field("flagged", description="Films shown: flagged, all or scheduled")


class KioskCinemaSchema(Schema):
    name: str = "Cinefin"
    logo_url: str | None = Field(None, description="Uploaded web logo URL, if any")
    accent_color: str | None = Field(None, description="Validated accent colour override, if any")
    time_format: str = Field("24h", description="Clock format: 12h or 24h (display.time_format)")


class KioskDisplayDataSchema(Schema):
    films: list[KioskFilmSchema] = Field(default_factory=list, description="Films on the marquee")
    screenings: list[KioskScreeningSchema] = Field(default_factory=list, description="Upcoming screenings")
    settings: KioskDisplaySettingsSchema
    cinema: KioskCinemaSchema
    reload_key: str = Field(..., description="Deploy stamp — a change means 'reload for new code'")


class KioskDisplayResponseSchema(SuccessResponseSchema):
    data: KioskDisplayDataSchema


kiosk_api = Router()


@kiosk_api.get("/display", response={200: KioskDisplayResponseSchema, 500: ErrorResponseSchema})
def get_kiosk_display(request: HttpRequest):
    films, screenings = kiosk_service.build_kiosk_content()
    return {
        "message": "Kiosk display data retrieved",
        "data": {
            "films": films,
            "screenings": screenings,
            "settings": KioskDisplaySettingsSchema(**Settings.get_all().get("kiosk", {})),
            "cinema": {
                "name": Settings.get("cinema.name") or "Cinefin",
                "logo_url": branding.web_logo_url(Settings.get("cinema.web_logo_path")),
                "accent_color": branding.valid_accent_color(Settings.get("display.accent_color")),
                "time_format": "12h" if Settings.get("display.time_format") == "12h" else "24h",
            },
            "reload_key": kiosk_service.spa_reload_key(),
        },
    }
