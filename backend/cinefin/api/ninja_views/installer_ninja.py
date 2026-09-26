"""Installer API for first-run Cinefin setup."""

import logging

import requests
from django.db import transaction
from ninja import Router, Schema, Status
from pydantic import Field

from ..exceptions import BadRequestError, InternalServerError, ValidationError
from ..models import Settings, SyncSource
from ..schemas.base import ErrorResponseSchema

logger = logging.getLogger(__name__)

installer_api = Router()

VALID_SYNC_TYPES = ("plex", "jellyfin")

RESUMABLE_WIZARD_STEPS = (2, 3, 4, 5)


class StatusSchema(Schema):
    configured: bool = Field(..., description="Whether first-run setup is complete")
    cinema_name: str | None = Field(None, description="Configured cinema name, if any")
    wizard_step: int = Field(0, description="Wizard step still in progress (2-5), or 0 when the wizard is finished")


class TestInput(Schema):
    sync_type: str = Field(..., description="plex / jellyfin")
    url: str = Field(..., min_length=1)
    token: str = Field(..., min_length=1)


class TestResponse(Schema):
    success: bool = True
    message: str
    libraries: list[str] | None = None


class MediaSourceInput(Schema):
    sync_type: str = Field(..., description="plex / jellyfin")
    url: str = Field(..., min_length=1)
    token: str = Field(..., min_length=1)
    libraries: str = Field("Films,Movies", description="Comma-separated library names")


class CompleteInput(Schema):
    cinema_name: str = Field(..., min_length=1, max_length=255)
    ratings_system: str = Field("BBFC", description="Ratings classification system: BBFC or MPAA")
    media_source: MediaSourceInput | None = Field(None, description="Optional media server to sync from")
    start_sync: bool = Field(False, description="Kick off an initial sync of the new source")
    admin_username: str | None = Field(None, description="Admin username (defaults to 'admin')")
    admin_password: str | None = Field(None, description="Admin password; blank leaves authentication off")


class MessageResponse(Schema):
    success: bool = True
    message: str


class WizardStepInput(Schema):
    step: int = Field(..., description="Wizard step reached (2-5), or 0 to mark the wizard finished")


def _fetch_libraries(sync_type: str, url: str, token: str) -> list[str]:
    """Connect to the media server and return its movie library names (movies-only, like the sync plugins)."""
    session = requests.Session()
    base = url.rstrip("/")

    if sync_type == "jellyfin":
        from ..utils.jellyfin import auth_header

        headers = {"Authorization": auth_header(token)}
        session.get(f"{base}/System/Info", headers=headers, timeout=10).raise_for_status()
        resp = session.get(f"{base}/Library/VirtualFolders", headers=headers, timeout=10)
        resp.raise_for_status()
        return [lib["Name"] for lib in resp.json() if lib.get("CollectionType") == "movies"]

    if sync_type == "plex":
        headers = {"X-Plex-Token": token}
        session.get(f"{base}/", headers=headers, timeout=10).raise_for_status()
        resp = session.get(f"{base}/library/sections", headers=headers, timeout=10)
        resp.raise_for_status()
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.content)
        return [d.get("title") for d in root.findall(".//Directory") if d.get("type") == "movie"]

    raise ValueError(f"Unsupported sync type: {sync_type}")


def _start_initial_sync(source: SyncSource) -> None:
    try:
        from ..sync.service import SyncManager

        SyncManager.enqueue(source.id)
    except Exception as e:  # noqa: BLE001
        logger.error("Initial sync for '%s' failed to queue: %s", source.name, e)


@installer_api.get("/status", response=StatusSchema, tags=["Installer"])
def get_status(request):
    step = Settings.get("setup.wizard_step") or 0
    return {
        "configured": bool(Settings.get("setup.completed")),
        "cinema_name": Settings.get("cinema.name") if Settings.objects.exists() else None,
        "wizard_step": step if step in RESUMABLE_WIZARD_STEPS else 0,
    }


@installer_api.post("/wizard-step", response={200: MessageResponse, 400: ErrorResponseSchema}, tags=["Installer"])
def set_wizard_step(request, payload: WizardStepInput):
    if payload.step not in (0, *RESUMABLE_WIZARD_STEPS):
        raise ValidationError(f"step must be one of 0, {', '.join(str(s) for s in RESUMABLE_WIZARD_STEPS)}")
    Settings.set("setup.wizard_step", payload.step)
    return Status(200, {"success": True, "message": f"Wizard step set to {payload.step}"})


@installer_api.post("/test-connection", response={200: TestResponse, 400: ErrorResponseSchema}, tags=["Installer"])
def test_connection(request, payload: TestInput):
    if payload.sync_type not in VALID_SYNC_TYPES:
        raise ValidationError(f"Unsupported type: {payload.sync_type}")
    try:
        libraries = _fetch_libraries(payload.sync_type, payload.url, payload.token)
        return Status(200, {"success": True, "message": "Connected successfully", "libraries": libraries})
    except requests.exceptions.Timeout:
        raise BadRequestError("Connection timed out — check the server URL") from None
    except requests.exceptions.ConnectionError:
        raise BadRequestError("Could not reach the server — check the URL and network") from None
    except requests.exceptions.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        msg = "Authentication failed — check your token" if code == 401 else f"Server returned HTTP {code}"
        raise BadRequestError(msg) from e
    except Exception as e:  # noqa: BLE001
        raise BadRequestError(f"Connection failed: {e}") from e


@installer_api.post(
    "/complete",
    response={200: MessageResponse, 400: ErrorResponseSchema, 500: ErrorResponseSchema},
    tags=["Installer"],
)
def complete_setup(request, payload: CompleteInput):
    # Auth-exempt and can set the admin password, so it must refuse once setup
    # has completed — the SPA calls it exactly once (end of step 1).
    if Settings.get("setup.completed"):
        raise ValidationError("Setup is already complete — change configuration in Settings instead")

    name = payload.cinema_name.strip()
    if not name:
        raise ValidationError("Cinema name is required")

    if payload.ratings_system not in ("BBFC", "MPAA"):
        raise ValidationError("ratings_system must be BBFC or MPAA")

    ms = payload.media_source
    if ms and ms.sync_type not in VALID_SYNC_TYPES:
        raise ValidationError(f"Unsupported media source type: {ms.sync_type}")

    admin_password = (payload.admin_password or "").strip()

    try:
        created_source = None
        with transaction.atomic():
            Settings.set("cinema.name", name)
            Settings.set("cinema.ratings_system", payload.ratings_system)

            if admin_password:
                from django.contrib.auth import login

                from ..services import auth_service

                user = auth_service.set_password(admin_password, username=payload.admin_username)
                auth_service.enable_auth()
                # Gate goes live immediately; log this session in so post-finalise steps work.
                login(request, user)

            if ms and ms.url.strip() and ms.token.strip():
                base = ms.sync_type.capitalize()
                source_name, n = base, 2
                while SyncSource.objects.filter(name=source_name).exists():
                    source_name, n = f"{base} {n}", n + 1
                created_source = SyncSource.objects.create(
                    name=source_name,
                    sync_type=ms.sync_type,
                    url=ms.url.strip(),
                    token=ms.token.strip(),
                    libraries=ms.libraries or "Films,Movies",
                    enabled=True,
                )

            Settings.set("setup.completed", True)
            Settings.set("setup.wizard_step", 2)

        if created_source and payload.start_sync:
            _start_initial_sync(created_source)

        return Status(200, {"success": True, "message": "Setup complete"})
    except Exception as e:  # noqa: BLE001
        logger.error("Setup completion failed: %s", e)
        raise InternalServerError(f"Setup failed: {e}") from e
