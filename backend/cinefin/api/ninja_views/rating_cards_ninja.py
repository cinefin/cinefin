"""Certification card asset management (source chain: static_video > custom_bg > bundled_bg; see api/utils/assets.py)."""

import io
import logging
import os

from django.conf import settings as django_settings
from django.http import HttpRequest, HttpResponse
from ninja import Field, File, Form, Router, Schema, Status, UploadedFile

from cinefin.api.exceptions import NotFoundError, ValidationError
from cinefin.api.models import Certification, Settings
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.utils.assets import rating_card_path, rating_card_video_path
from cinefin.api.utils.media_paths import usermedia_abs_path
from cinefin.api.utils.paths import contained_in

logger = logging.getLogger(__name__)

rating_cards_api = Router()

ALLOWED_UPLOADS = {".jpg": "background", ".jpeg": "background", ".mp4": "video"}


class RatingCardSchema(Schema):
    certification: str = Field(..., description="Certificate value (e.g. 'PG')")
    source: str = Field(
        ..., description="Effective card source: static_video | custom_background | bundled_background | none"
    )
    static_video: bool = Field(..., description="A user static card video exists")
    custom_background: bool = Field(..., description="A user background override exists")
    bundled_background: bool = Field(..., description="A bundled background exists")
    generated_count: int = Field(..., description="Generated card rows currently in the database")


class RatingCardListSchema(Schema):
    system: str
    cards: list[RatingCardSchema]


class RatingCardListResponseSchema(SuccessResponseSchema):
    data: RatingCardListSchema


def _validate_system_and_cert(system: str, certification: str | None = None) -> None:
    if system not in Settings.VALID_RATINGS_SYSTEMS:
        raise ValidationError(f"Unknown ratings system '{system}'", error_code="INVALID_RATINGS_SYSTEM")
    if certification is not None and certification not in Settings.get_valid_ratings(system):
        raise ValidationError(
            f"'{certification}' is not a valid {system} certificate", error_code="INVALID_CERTIFICATION"
        )


def _override_path(system: str, certification: str, kind: str) -> str:
    ext = "mp4" if kind == "video" else "jpg"
    return os.path.join(django_settings.MEDIA_ROOT, "ratings", system, f"{certification}.{ext}")


def _custom_background_path(system: str, certification: str) -> str | None:
    for candidate in (
        _override_path(system, certification, "background"),
        os.path.join(django_settings.MEDIA_ROOT, "ratings", f"{certification}.jpg"),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def _purge_generated_cards(system: str, certification: str) -> int:
    # Files outside the generated-cards directory (static cards) are never deleted.
    certifications_dir = os.path.join(django_settings.MEDIA_ROOT, "certifications")
    rows = Certification.objects.filter(ratings_system=system, certification=certification)
    purged = rows.count()
    for row in rows:
        if row.file_path:
            real = os.path.realpath(usermedia_abs_path(row.file_path))
            if contained_in(real, certifications_dir) and os.path.exists(real):
                try:
                    os.remove(real)
                except OSError as e:
                    logger.warning(f"Could not delete generated card {real}: {e}")
    rows.delete()
    return purged


@rating_cards_api.get("", response={200: RatingCardListResponseSchema, 400: ErrorResponseSchema})
def list_rating_cards(request: HttpRequest, system: str):
    """Card sources per certificate, in severity order."""
    _validate_system_and_cert(system)

    cards = []
    for cert in Settings.get_ratings_order(system):
        static_video = rating_card_video_path(system, cert) is not None
        custom_background = _custom_background_path(system, cert) is not None
        bundled = os.path.exists(os.path.join(django_settings.CINEFIN_ASSETS_DIR, "ratings", system, f"{cert}.jpg"))
        if static_video:
            source = "static_video"
        elif custom_background:
            source = "custom_background"
        elif bundled:
            source = "bundled_background"
        else:
            source = "none"
        cards.append(
            RatingCardSchema(
                certification=cert,
                source=source,
                static_video=static_video,
                custom_background=custom_background,
                bundled_background=bundled,
                generated_count=Certification.objects.filter(ratings_system=system, certification=cert).count(),
            )
        )
    return Status(200, RatingCardListResponseSchema(data=RatingCardListSchema(system=system, cards=cards)))


@rating_cards_api.post(
    "/upload", response={200: MessageResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def upload_rating_card(
    request: HttpRequest,
    system: str = Form(..., description="Ratings system (BBFC/MPAA)"),
    certification: str = Form(..., description="Certificate value"),
    file: UploadedFile = File(..., description=".jpg background or .mp4 static card"),
):
    _validate_system_and_cert(system, certification)

    ext = os.path.splitext(file.name or "")[1].lower()
    kind = ALLOWED_UPLOADS.get(ext)
    if not kind:
        raise ValidationError(
            "Upload a .jpg background or a .mp4 static card video", error_code="INVALID_FILE_EXTENSION"
        )

    dest = _override_path(system, certification, kind)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as out:
        for chunk in file.chunks():
            out.write(chunk)

    purged = _purge_generated_cards(system, certification)
    what = "static card video" if kind == "video" else "card background"
    logger.info(f"Uploaded {what} for {system}/{certification}; purged {purged} generated card(s)")
    return Status(200, MessageResponseSchema(message=f"Saved {what} for {certification}"))


@rating_cards_api.delete("", response={200: MessageResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema})
def delete_rating_card_override(request: HttpRequest, system: str, certification: str, kind: str):
    """Remove a user override (kind=video|background); bundled backgrounds can't be removed."""
    _validate_system_and_cert(system, certification)
    if kind not in ("video", "background"):
        raise ValidationError("kind must be 'video' or 'background'", error_code="INVALID_KIND")

    if kind == "background":
        path = _custom_background_path(system, certification)
    else:
        path = rating_card_video_path(system, certification)

    if not path or not path.startswith(os.path.join(django_settings.MEDIA_ROOT, "")):
        raise NotFoundError(f"No {kind} override for {system}/{certification}")

    os.remove(path)
    purged = _purge_generated_cards(system, certification)
    logger.info(f"Removed {kind} override for {system}/{certification}; purged {purged} generated card(s)")
    return Status(200, MessageResponseSchema(message=f"Removed {kind} override for {certification}"))


@rating_cards_api.get("/preview", response={400: ErrorResponseSchema, 404: ErrorResponseSchema})
def preview_rating_card(request: HttpRequest, system: str, certification: str):
    """PNG render of the composed card (sample title); 404 when there is no background to compose from."""
    from cinefin.api.services.certification_service import CertificationService

    _validate_system_and_cert(system, certification)

    background = rating_card_path(system, certification)
    if not background:
        raise NotFoundError(f"No card background for {system}/{certification}")

    title = "YOUR FILM TITLE" if system in CertificationService.TITLE_CARD_SYSTEMS else None
    frame = CertificationService._compose_card_frame(background_path=background, title=title)
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")
