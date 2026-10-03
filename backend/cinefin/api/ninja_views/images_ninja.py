"""Image libraries: the images title templates and ticket designs place. One implementation over
two folders; deleting an image a template or design still uses is refused, naming its users."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from django.conf import settings
from django.http import HttpRequest
from ninja import Field, File, Router, Schema, Status
from ninja.files import UploadedFile
from PIL import Image

from cinefin.api.exceptions import ConflictError, NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.ninja_views.media.utils import sanitize_filename
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema

images_api = Router()

MAX_BYTES = 5 * 1024 * 1024
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}


def _title_users(name: str) -> list[str]:
    from cinefin.api.models import ProgrammeTitleTemplate

    return [
        t.name
        for t in ProgrammeTitleTemplate.objects.all()
        if any(
            el.get("type") == "image" and os.path.basename(str(el.get("path") or "")) == name
            for el in (t.template_config or {}).get("elements", [])
        )
    ]


def _ticket_users(name: str) -> list[str]:
    from cinefin.api.models import TicketDesign

    return [
        d.name
        for d in TicketDesign.objects.all()
        if any(el.get("type") == "image" and el.get("file") == name for el in d.elements or [])
    ]


@dataclass(frozen=True)
class Library:
    subdir: str
    types: tuple[str, ...]
    url: Callable[[str], str]
    users: Callable[[str], list[str]]

    @property
    def directory(self) -> str:
        return os.path.join(settings.MEDIA_ROOT, self.subdir)

    def accepts(self, filename: str) -> bool:
        exts = {EXTENSIONS[t] for t in self.types} | ({".jpeg"} if "image/jpeg" in self.types else set())
        return filename.lower().endswith(tuple(exts))


LIBRARIES = {
    "titles": Library(
        subdir="programme_title_images",
        types=("image/png", "image/jpeg"),
        url=lambda n: f"{settings.MEDIA_URL}programme_title_images/{quote(n)}",
        users=_title_users,
    ),
    "tickets": Library(
        subdir="ticket_images",
        types=("image/png", "image/jpeg", "image/gif"),
        url=lambda n: f"/api/v2/tickets/preview/asset?kind=image&file={quote(n)}",
        users=_ticket_users,
    ),
}


class ImageSchema(Schema):
    name: str = Field(description="File name (the id within its library)")
    url: str = Field(description="Where the image is served")
    width: int | None = None
    height: int | None = None


class ImageListResponseSchema(SuccessResponseSchema):
    data: list[ImageSchema]


class ImageResponseSchema(SuccessResponseSchema):
    data: ImageSchema


def _library(library: str) -> Library:
    if library not in LIBRARIES:
        raise NotFoundError(f"Unknown image library '{library}'", error_code="IMAGE_LIBRARY_NOT_FOUND")
    return LIBRARIES[library]


def _entry(lib: Library, name: str) -> dict:
    width = height = None
    try:
        with Image.open(os.path.join(lib.directory, name)) as img:
            width, height = img.width, img.height
    except Exception:  # noqa: BLE001 — a corrupt file still lists, just without dimensions
        pass
    return {"name": name, "url": lib.url(name), "width": width, "height": height}


@images_api.get("/{library}", response={200: ImageListResponseSchema, 404: ErrorResponseSchema})
def list_images(request: HttpRequest, library: str):
    lib = _library(library)
    names = sorted(os.listdir(lib.directory), key=str.lower) if os.path.isdir(lib.directory) else []
    images = [_entry(lib, n) for n in names if lib.accepts(n)]
    return {"message": "Images retrieved", "data": images}


@images_api.post("/{library}", response={201: ImageResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema})
def upload_image(request: HttpRequest, library: str, file: UploadedFile = File(...)):
    lib = _library(library)
    if file.content_type not in lib.types:
        kinds = ", ".join(t.split("/")[1].upper() for t in lib.types)
        raise ValidationError(f"Upload a {kinds} image", error_code="INVALID_FILE_TYPE")
    if file.size > MAX_BYTES:
        raise ValidationError("File too large. Maximum size is 5MB", error_code="FILE_TOO_LARGE")

    os.makedirs(lib.directory, exist_ok=True)
    base, ext = os.path.splitext(sanitize_filename(os.path.basename(file.name or "image")))
    if not lib.accepts(base + ext):
        ext = EXTENSIONS[file.content_type]
    name, n = base + ext, 1
    while os.path.exists(os.path.join(lib.directory, name)):
        name, n = f"{base} ({n}){ext}", n + 1
    try:
        with open(os.path.join(lib.directory, name), "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)
    except OSError as e:
        raise UnprocessableEntityError(f"Could not store the image: {e}", error_code="IMAGE_UPLOAD_FAILED") from e
    return Status(201, {"message": "Image uploaded", "data": _entry(lib, name)})


@images_api.delete(
    "/{library}/{name}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 409: ErrorResponseSchema}
)
def delete_image(request: HttpRequest, library: str, name: str):
    lib = _library(library)
    name = os.path.basename(name)
    path = os.path.join(lib.directory, name)
    if not os.path.isfile(path):
        raise NotFoundError("Image not found", error_code="IMAGE_NOT_FOUND")
    if users := lib.users(name):
        raise ConflictError(f"Still used by {', '.join(users)} — remove it there first", error_code="IMAGE_IN_USE")
    os.remove(path)
    return {"message": f'Deleted "{name}"'}
