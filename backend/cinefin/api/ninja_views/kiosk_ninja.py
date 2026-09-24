"""Kiosk display API — the SPA wall display's single read-only data source."""

import logging

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.schemas.base import ErrorResponseSchema, SuccessResponseSchema
from cinefin.api.services import kiosk_service

logger = logging.getLogger(__name__)


class KioskFilmSchema(Schema):
    id: int = Field(..., description="Movie ID")
    title: str = Field(..., description="Movie title")
    year: int | None = Field(None, description="Release year")
    cert: str = Field("", description="Certificate for the active ratings system")
    runtime: int = Field(0, description="Runtime in minutes")
    genres: list[str] = Field(default_factory=list, description="Up to three genres")
    synopsis: str = Field("", description="Synopsis")
    poster: str | None = Field(None, description="Poster thumbnail URL")
    director: str = Field("", description="Director")


class KioskScreeningSchema(Schema):
    id: int = Field(..., description="Schedule ID")
    programme: str = Field(..., description="Programme name")
    start: str = Field(..., description="Start time (ISO)")
    end: str = Field(..., description="End time (ISO)")
    runtime: int = Field(..., description="Runtime in minutes")
    status: str = Field(..., description="Schedule status (scheduled or running)")
    feature: KioskFilmSchema | None = Field(None, description="First feature — single-poster contexts")
    features: list[KioskFilmSchema] = Field(
        default_factory=list, description="Every feature, in running order, de-duplicated"
    )


class KioskDisplaySettingsSchema(Schema):
    layout: str = Field("wall", description="Base layout (wall, spotlight, split, board, tonight, auto)")
    rotate_minutes: int = Field(0, description="Cycle ambient layouts every N minutes (0 = off)")
    header: bool = Field(True, description="Show the cinema name/logo header")
    clock: bool = Field(True, description="Show the clock")
    takeover: bool = Field(True, description="Now Showing takeover while a programme is live")
    countdown_minutes: int = Field(30, description="Countdown engage threshold in minutes (0 = off)")
    night: bool = Field(False, description="Dim to a clock during quiet hours")
    night_start: str = Field("01:00", description="Night hours start (HH:MM)")
    night_end: str = Field("08:00", description="Night hours end (HH:MM)")
    content_source: str = Field("flagged", description="Films shown: flagged, all or scheduled")
    show_showtimes: bool = Field(True, description="Show next showtimes on poster-wall tiles")


class KioskCinemaSchema(Schema):
    name: str = Field("Cinefin", description="Cinema name")
    logo_url: str | None = Field(None, description="Uploaded web logo URL, if any")
    accent_color: str | None = Field(None, description="Validated accent colour override, if any")
    time_format: str = Field("24h", description="Clock format: 12h or 24h (display.time_format)")


class KioskDisplayDataSchema(Schema):
    films: list[KioskFilmSchema] = Field(default_factory=list, description="Films on the marquee")
    screenings: list[KioskScreeningSchema] = Field(default_factory=list, description="Upcoming screenings")
    settings: KioskDisplaySettingsSchema = Field(..., description="Kiosk settings (server-side defaults)")
    cinema: KioskCinemaSchema = Field(..., description="Cinema branding / clock format")
    reload_key: str = Field(..., description="Deploy stamp — a change means 'reload for new code'")


class KioskDisplayResponseSchema(SuccessResponseSchema):
    data: KioskDisplayDataSchema = Field(..., description="Kiosk display data")


kiosk_api = Router()


@kiosk_api.get("/display", response={200: KioskDisplayResponseSchema, 500: ErrorResponseSchema})
def get_kiosk_display(request: HttpRequest):
    from cinefin.api.models import Settings
    from cinefin.api.utils import branding

    films, screenings = kiosk_service.build_kiosk_content()
    kiosk_settings = Settings.get_all().get("kiosk", {})

    cinema = KioskCinemaSchema(
        name=Settings.get("cinema.name") or "Cinefin",
        logo_url=branding.web_logo_url(Settings.get("cinema.web_logo_path")),
        accent_color=branding.valid_accent_color(Settings.get("display.accent_color")),
        time_format="12h" if Settings.get("display.time_format") == "12h" else "24h",
    )

    return Status(
        200,
        KioskDisplayResponseSchema(
            message="Kiosk display data retrieved",
            data=KioskDisplayDataSchema(
                films=films,
                screenings=screenings,
                settings=KioskDisplaySettingsSchema(**kiosk_settings),
                cinema=cinema,
                reload_key=kiosk_service.spa_reload_key(),
            ),
        ),
    )
