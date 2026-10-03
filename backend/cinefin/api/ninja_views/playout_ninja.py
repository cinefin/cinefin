"""Programme-level playout: cue (/load), the status, every transport action (/control), manual play
and the playout hosts. Raw player settings (volume, speed, tracks) live in mpv_ninja.py."""

import logging
import re
from typing import Any, Literal
from urllib.parse import urlparse

from django.http import HttpRequest
from django.utils import timezone
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import ConflictError, NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Bumper, Movie, Playlist, PlayoutHost, Programme, Trailer
from cinefin.api.mpv_service import mpv_service
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.schemas.playout import PlayoutStatusDataSchema, ProgrammeInfoSchema
from cinefin.api.services import playout_discovery, playout_link, standby
from cinefin.api.services.block_types import resolve_media_path
from cinefin.api.services.playlist_utils import PlaylistUtils
from cinefin.api.services.playout_agent_service import PROTOCOL, playout_agent_service
from cinefin.api.services.playout_host_service import playout_host_service
from cinefin.api.services.playout_service import perform, playout_status, programme_info, require

logger = logging.getLogger(__name__)


class PlaylistInfoSchema(Schema):
    id: int
    item_count: int
    created: bool = Field(..., description="Whether this load (re)generated the playlist")


class MPVStatusSchema(Schema):
    paused: bool
    position: int
    playlist_count: int


class LoadProgrammeSchema(Schema):
    programme_id: int
    generate_playlist: bool | None = Field(True, description="Generate the playlist if missing or stale")


class LoadProgrammeDataSchema(Schema):
    programme: ProgrammeInfoSchema
    playlist: PlaylistInfoSchema
    status: str
    mpv_status: MPVStatusSchema
    warnings: list[str] = Field(
        default_factory=list, description="Pre-flight warnings: items whose media is unreachable"
    )


class LoadProgrammeResponseSchema(SuccessResponseSchema):
    data: LoadProgrammeDataSchema


class PlayoutStatusResponseSchema(SuccessResponseSchema):
    data: PlayoutStatusDataSchema


class ControlPlayoutSchema(Schema):
    action: Literal[
        "start", "pause", "resume", "previous", "next", "seek", "jump", "end_hold", "end", "recover", "dismiss"
    ] = Field(..., description="A transport action; it must be in the status's actions (else 409)")
    seconds: float | None = Field(None, description="seek: to this many seconds into the item on screen")
    offset: float | None = Field(None, description="seek: by this many seconds (negative is back)")
    index: int | None = Field(None, description="jump: to this player playlist index")


class MPVPlaylistItemSchema(Schema):
    index: int
    title: str
    type: str
    file: str
    duration: float | None = None
    current: bool
    programme_position: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PlaylistDataSchema(Schema):
    playlist: list[MPVPlaylistItemSchema]
    current_index: int
    total_items: int
    programme_offset: int = Field(..., description="Player index of the programme's first item")
    total_duration: float
    elapsed_time: float
    remaining_time: float


class PlayoutPlaylistResponseSchema(SuccessResponseSchema):
    data: PlaylistDataSchema


playout_api = Router()


@playout_api.post(
    "/load",
    response={
        200: LoadProgrammeResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def load_programme(request: HttpRequest, data: LoadProgrammeSchema):
    """Cue a programme. Refused (409) while one is on air: end it first."""
    programme = Programme.objects.filter(pk=data.programme_id).first()
    if programme is None:
        raise NotFoundError("Programme not found")
    require("cue")

    playlist = Playlist.objects.filter(programme=programme).first()
    playlist_created = False

    if data.generate_playlist and (playlist is None or programme.playlist_stale):
        reason = "missing" if playlist is None else "stale"
        logger.info(f"Generating {reason} playlist for programme {data.programme_id}")
        from cinefin.api.services import ProgrammeService

        if ProgrammeService.refresh_playlist(programme) is None:
            raise UnprocessableEntityError("Failed to generate playlist — check the application logs")
        playlist = Playlist.objects.get(programme=programme)
        playlist_created = True
    elif playlist is None:
        raise ValidationError("Programme has no playlist. Set generate_playlist=true to create one.")

    from cinefin.api.services.playlist_service import PlaylistService

    preflight_warnings = PlaylistService.verify_playlist_availability(playlist)

    playout_agent_service.ensure_mpv_running()
    if not mpv_service.load_programme(programme):
        raise UnprocessableEntityError("Failed to load programme into playout system")

    snap = mpv_service.snapshot() or {}

    return Status(
        200,
        LoadProgrammeResponseSchema(
            success=True,
            data=LoadProgrammeDataSchema(
                programme=programme_info(programme),
                playlist=PlaylistInfoSchema(
                    id=playlist.id, item_count=playlist.items.count(), created=playlist_created
                ),
                status="loaded",
                mpv_status=MPVStatusSchema(
                    paused=snap.get("pause", True),
                    position=snap.get("pos") or 0,
                    playlist_count=len(mpv_service.get_playlist() or []),
                ),
                warnings=preflight_warnings,
            ),
        ),
    )


@playout_api.get("/status", response={200: PlayoutStatusResponseSchema})
def get_playout_status(request: HttpRequest):
    """The playout status (also pushed on the WebSocket's "playout" channel)."""
    return Status(200, PlayoutStatusResponseSchema(message="Playout status", data=playout_status()))


@playout_api.post(
    "/control",
    response={
        200: PlayoutStatusResponseSchema,
        400: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def control_playout(request: HttpRequest, data: ControlPlayoutSchema):
    """Every transport button: start, pause, resume, previous, next, seek, jump, end_hold and end
    (to standby). An action the status doesn't list in `actions` is refused with a 409."""
    perform(data.action, seconds=data.seconds, offset=data.offset, index=data.index)
    return Status(200, PlayoutStatusResponseSchema(message=f"Done: {data.action}", data=playout_status()))


@playout_api.post("/reset", response={200: MessageResponseSchema, 422: ErrorResponseSchema})
def reset_playout(request: HttpRequest):
    """Clear any loaded programme or manual queue and put the player on standby."""
    if not mpv_service.standby():
        raise UnprocessableEntityError("Could not reach the player", error_code="PLAYER_UNREACHABLE")
    return Status(200, MessageResponseSchema(message="Player on standby"))


class ManualAddSchema(Schema):
    kind: Literal["movie", "trailer", "media", "url"]
    id: int | None = Field(None, description="The film, trailer or media item (not for a URL)")
    url: str | None = Field(None, description="An http(s) stream URL (kind 'url' only)")
    now: bool = Field(False, description="Play it now instead of adding it to the end of the queue")
    end_programme: bool = Field(False, description="End a loaded programme first (else 409)")


class ManualMoveSchema(Schema):
    to: int


_MANUAL_MODELS = {"movie": Movie, "trailer": Trailer, "media": Bumper}


def _manual_source(data: ManualAddSchema) -> tuple[str, str]:
    """(title, stream URL) for a manual item."""
    if data.kind == "url":
        url = (data.url or "").strip()
        if not re.match(r"^https?://", url):
            raise ValidationError("Enter an http:// or https:// URL")
        return url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or url, url
    obj = _MANUAL_MODELS[data.kind].objects.filter(id=data.id).first()
    if obj is None:
        raise NotFoundError(f"No such {data.kind}")
    url = resolve_media_path(obj)
    if not url:
        raise UnprocessableEntityError(f"'{obj.title}' has no stream", error_code="NO_STREAM")
    year = getattr(obj, "year", None)
    return (f"{obj.title} ({year})" if year else obj.title), url


@playout_api.post("/manual", response={200: MessageResponseSchema, 409: ErrorResponseSchema, 422: ErrorResponseSchema})
def manual_add(request: HttpRequest, data: ManualAddSchema):
    """Manual mode: play or queue a film, trailer, media item or URL outside any programme."""
    title, url = _manual_source(data)
    if mpv_service.current_programme is not None:
        if not data.end_programme:
            raise ConflictError(
                f"'{mpv_service.current_programme.name}' is loaded",
                error_code="PROGRAMME_LOADED",
            )
        mpv_service.standby()
    if not mpv_service.manual_add(title, data.kind, url, now=data.now):
        raise UnprocessableEntityError("The player didn't take the item", error_code="PLAYER_UNREACHABLE")
    return Status(200, MessageResponseSchema(message=f"{'Playing' if data.now else 'Queued'} {title}"))


@playout_api.delete("/manual/{int:index}", response={200: MessageResponseSchema, 422: ErrorResponseSchema})
def manual_remove(request: HttpRequest, index: int):
    if not mpv_service.manual_remove(index):
        raise UnprocessableEntityError("Couldn't remove that item", error_code="MANUAL_REMOVE_FAILED")
    return Status(200, MessageResponseSchema(message="Removed from the queue"))


@playout_api.post("/manual/{int:index}/move", response={200: MessageResponseSchema, 422: ErrorResponseSchema})
def manual_move(request: HttpRequest, index: int, data: ManualMoveSchema):
    if not mpv_service.manual_move(index, data.to):
        raise UnprocessableEntityError("Couldn't move that item", error_code="MANUAL_MOVE_FAILED")
    return Status(200, MessageResponseSchema(message="Queue reordered"))


@playout_api.get("/playlist", response={200: PlayoutPlaylistResponseSchema, 500: ErrorResponseSchema})
def get_playlist(request: HttpRequest):
    """The player's playlist, programme items filled in from the database (jump with /control)."""
    playlist_info = mpv_service.get_playlist_info()
    current_index = playlist_info.get("current_index", 0)
    programme_offset = playlist_info.get("programme_offset", 0)
    current_playlist = mpv_service.current_playlist
    enhanced_playlist = [
        PlaylistUtils.enhance_mpv_playlist_item(item, current_playlist) for item in playlist_info.get("playlist", [])
    ]

    timing_info = {"total_duration": 0.0, "elapsed_time": 0.0, "remaining_time": 0.0}
    if current_playlist:
        try:
            order = current_index - programme_offset if current_index >= programme_offset else None
            time_pos = (mpv_service.snapshot() or {}).get("time") or 0
            playlist_items = current_playlist.items.all().order_by("order")
            timing_info = PlaylistUtils.calculate_playlist_timing(playlist_items, order, time_pos)
        except Exception as e:
            logger.warning(f"Could not calculate timing information: {e}")

    return Status(
        200,
        PlayoutPlaylistResponseSchema(
            success=True,
            data=PlaylistDataSchema(
                playlist=enhanced_playlist,
                current_index=current_index,
                total_items=playlist_info.get("total_items", 0),
                programme_offset=programme_offset,
                total_duration=timing_info["total_duration"],
                elapsed_time=timing_info["elapsed_time"],
                remaining_time=timing_info["remaining_time"],
            ),
        ),
    )


# The playout agent (cinefin-playout): start, stop and inspect the mpv process itself.


class AgentStatusDataSchema(Schema):
    enabled: bool
    reachable: bool
    agent_version: str | None = None
    mpv_running: bool = False
    mpv_mode: str | None = None
    mpv_pid: int | None = None
    uptime_seconds: float | None = None
    restarts: int = Field(default=0, description="Crash-restarts performed by the agent")
    socket_responding: bool = False
    error: str | None = Field(default=None, description="Why the agent is unreachable, if it is")
    warning: str | None = Field(
        default=None, description="A player problem to show: a local mpv too old, or a standby ident download failure"
    )


class AgentStatusResponseSchema(SuccessResponseSchema):
    data: AgentStatusDataSchema


class AgentActionDataSchema(Schema):
    ok: bool
    action_message: str
    mpv_running: bool


class AgentActionResponseSchema(SuccessResponseSchema):
    data: AgentActionDataSchema


@playout_api.get("/agent/status", response={200: AgentStatusResponseSchema, 500: ErrorResponseSchema})
def get_agent_status(request: HttpRequest):
    """Status of the playout agent and its MPV process (unreachable/disabled is a result, always 200)."""
    active = PlayoutHost.get_active()
    if active is not None and active.kind == PlayoutHost.KIND_LOCAL_SOCKET:
        # No agent to poll — reachability is "is a local mpv answering on the
        # socket". There is no separate process query, so mpv_running == reachable.
        from cinefin.api.mpv_socket import probe_socket

        reachable, err = probe_socket(active.socket_path)
        return Status(
            200,
            AgentStatusResponseSchema(
                message="Local mpv reachable" if reachable else "Local mpv unreachable",
                data=AgentStatusDataSchema(
                    enabled=True,
                    reachable=reachable,
                    mpv_running=reachable,
                    socket_responding=reachable,
                    error=None if reachable else (err or "mpv is not answering on the socket"),
                    warning=mpv_service.player_warning or None,
                ),
            ),
        )
    if not playout_agent_service.is_configured():
        return Status(
            200,
            AgentStatusResponseSchema(
                message="No playout host configured",
                data=AgentStatusDataSchema(enabled=False, reachable=False),
            ),
        )
    try:
        status = playout_agent_service.get_status()
    except UnprocessableEntityError as e:
        return Status(
            200,
            AgentStatusResponseSchema(
                message="Playout agent unreachable",
                data=AgentStatusDataSchema(enabled=True, reachable=False, error=e.message),
            ),
        )
    _note_agent_version(status.get("agent_version"))
    mpv = status.get("mpv", {})
    standby_error = (status.get("standby") or {}).get("error")
    return Status(
        200,
        AgentStatusResponseSchema(
            message="Playout agent status retrieved",
            data=AgentStatusDataSchema(
                enabled=True,
                reachable=True,
                agent_version=status.get("agent_version"),
                mpv_running=bool(mpv.get("running")),
                mpv_mode=mpv.get("mode"),
                mpv_pid=mpv.get("pid"),
                uptime_seconds=mpv.get("uptime_seconds"),
                restarts=mpv.get("restarts", 0),
                socket_responding=bool(mpv.get("socket_responding")),
                warning=f"The standby ident did not download: {standby_error}" if standby_error else None,
            ),
        ),
    )


def _note_agent_version(version) -> None:
    """When the active player reports a version other than the one on record (it was updated),
    refresh its row, so its protocol and any "Update" badge follow without a manual refresh."""
    host = PlayoutHost.get_active()
    if host is None or host.kind != PlayoutHost.KIND_AGENT or not version or version == host.agent_version:
        return
    playout_host_service.refresh(host)


def _agent_action(action: str) -> AgentActionResponseSchema:
    active = PlayoutHost.get_active()
    if active is not None and active.kind == PlayoutHost.KIND_LOCAL_SOCKET:
        raise UnprocessableEntityError(
            "Starting, stopping and restarting the player needs the playout agent — "
            "a local mpv host is run and stopped by you.",
            error_code="AGENT_REQUIRED",
        )
    if not playout_agent_service.is_configured():
        raise UnprocessableEntityError(
            "No playout host is configured — add one on the Playout settings page", error_code="AGENT_DISABLED"
        )
    operations = {
        "start": playout_agent_service.start_mpv,
        "stop": playout_agent_service.stop_mpv,
        "restart": playout_agent_service.restart_mpv,
    }
    result = operations[action]()
    return AgentActionResponseSchema(
        message=f"MPV {action} requested",
        data=AgentActionDataSchema(
            ok=bool(result.get("ok")),
            action_message=result.get("message", ""),
            mpv_running=bool(result.get("status", {}).get("running")),
        ),
    )


@playout_api.post("/agent/start", response={200: AgentActionResponseSchema, 422: ErrorResponseSchema})
def agent_start_mpv(request: HttpRequest):
    return Status(200, _agent_action("start"))


@playout_api.post("/agent/stop", response={200: AgentActionResponseSchema, 422: ErrorResponseSchema})
def agent_stop_mpv(request: HttpRequest):
    return Status(200, _agent_action("stop"))


@playout_api.post("/agent/restart", response={200: AgentActionResponseSchema, 422: ErrorResponseSchema})
def agent_restart_mpv(request: HttpRequest):
    return Status(200, _agent_action("restart"))


class PlayoutHostSchema(Schema):
    id: int
    name: str
    kind: str = Field(default="agent", description="'agent' (WebSocket) or 'local_socket' (local mpv JSON-IPC)")
    base_url: str
    socket_path: str = ""
    has_token: bool = Field(description="Whether the host is paired (the token itself is never returned)")
    agent_id: str = Field("", description="The agent's stable id, from pairing")
    needs_pairing_again: bool = Field(
        False, description="An agent paired before pairing codes (a token but no agent id): remove it and pair again"
    )
    needs_update: bool = Field(
        False, description="The agent is older than this Cinefin needs (recorded on pairing and refresh)"
    )
    needs_cinefin_update: bool = Field(
        False, description="The agent no longer serves this Cinefin's protocol: update Cinefin (or use an older player)"
    )
    show_status: bool = True
    enabled: bool
    is_active: bool
    last_seen_at: str | None = None
    agent_version: str = ""
    os: str = ""
    arch: str = ""


class PlayoutHostListResponse(SuccessResponseSchema):
    data: list[PlayoutHostSchema]


class PlayoutHostResponse(SuccessResponseSchema):
    data: PlayoutHostSchema


class HostGraphicsSchema(Schema):
    mode: str = Field(
        "desktop",
        description='"desktop" (X/Wayland session), "drm" (headless KMS) or "android" (an Android TV player)',
    )
    vo: str = "gpu-next"
    gpu_api: str = Field("", description='"" = mpv default; e.g. "d3d11", "vulkan"')
    gpu_context: str = Field("", description='"" = auto; e.g. "displayvk", "drm"')
    hwdec: str = Field("auto", description="hardware decoding: auto / auto-safe / no / nvdec / vaapi / …")
    screen: int = Field(0, description="desktop mode: which display index to fullscreen on")
    drm_connector: str = Field("", description='drm mode: e.g. "HDMI-A-1"; "" = the first connected screen')
    drm_mode: str = Field("", description='drm mode: optional pinned mode, e.g. "1920x1080@60"')
    fullscreen: bool = True
    hdr_passthrough: bool = Field(True, description="send HDR to the display instead of tone-mapping to SDR")
    osc: bool = Field(False, description="mpv's own on-screen controller")
    display: str = Field("", description='desktop mode: X display, e.g. ":0"; empty for drm')
    display_mode: str = Field(
        "",
        description='android: the display mode, e.g. "3840x2160@23.976"; "" = the box\'s own (ignored by the desktop agent)',
    )
    keep_awake: bool = Field(
        True, description="android: keep the screen on so the box never goes to standby (ignored by the desktop agent)"
    )
    tunneling: bool = Field(
        False, description="android: tunnelled playback, A/V sync in the decoder (ignored by the desktop agent)"
    )


class HostAudioSchema(Schema):
    device: str = Field("", description='"" = mpv default; else a device id from /hardware')
    channels: str = Field("auto", description="auto / stereo / 5.1 / 7.1")
    spdif_passthrough: list[str] = Field(
        default_factory=list, description='codecs bitstreamed untouched, e.g. ["ac3", "dts"]'
    )
    max_volume: int = Field(130, ge=0, description="mpv volume-max (percent)")


class HostLaunchConfigSchema(Schema):
    autostart: bool = Field(True, description="launch mpv when the agent boots")
    graphics: HostGraphicsSchema = Field(default_factory=HostGraphicsSchema)
    audio: HostAudioSchema = Field(default_factory=HostAudioSchema)


class HostLaunchConfigResponse(SuccessResponseSchema):
    data: HostLaunchConfigSchema


class HostConfigSavedSchema(Schema):
    restart_required: bool = False


class HostConfigSavedResponse(SuccessResponseSchema):
    data: HostConfigSavedSchema


class HostScreenSchema(Schema):
    index: int
    name: str = ""
    w: int = 0
    h: int = 0
    hz: float = 0.0


class HostAudioDeviceSchema(Schema):
    name: str
    description: str = ""


class HostMPVInfoSchema(Schema):
    version: str = ""
    vo: list[str] = Field(default_factory=list)
    gpu_apis: list[str] = Field(default_factory=list)


class HostDisplayModeSchema(Schema):
    id: int
    w: int = 0
    h: int = 0
    hz: float = 0.0


class HostAndroidSchema(Schema):
    """What an Android TV player's output path can do."""

    device: str = Field("", description='e.g. "NVIDIA SHIELD Android TV"')
    sdk: int = Field(0, description="Android API level")
    passthrough: list[str] = Field(
        default_factory=list, description='encodings the receiver takes as a bitstream, e.g. ["ac3", "truehd"]'
    )
    max_channels: int = 0
    hdr: list[str] = Field(default_factory=list, description='HDR formats the display shows, e.g. ["HDR10", "HLG"]')
    modes: list[HostDisplayModeSchema] = Field(default_factory=list, description="the display's modes")


class HostHardwareSchema(Schema):
    audio_devices: list[HostAudioDeviceSchema] = Field(default_factory=list)
    drm_connectors: list[str] = Field(default_factory=list)
    screens: list[HostScreenSchema] = Field(default_factory=list)
    mpv: HostMPVInfoSchema = Field(default_factory=HostMPVInfoSchema)
    note: str = Field("", description="why a list is empty, e.g. no mpv binary found")
    android: HostAndroidSchema | None = Field(None, description="an Android TV player only")


class HostHardwareResponse(SuccessResponseSchema):
    data: HostHardwareSchema


class PlayoutHostInput(Schema):
    name: str | None = None
    kind: str | None = Field(
        default=None, description="'local_socket' on create (agent hosts are added by pairing); either on update"
    )
    base_url: str | None = None
    socket_path: str | None = None
    enabled: bool | None = None
    is_active: bool | None = None
    show_status: bool | None = None


class PairHostInput(Schema):
    base_url: str = Field(description="The player's address, e.g. http://10.0.0.5:8089 (scheme and port optional)")
    code: str = Field(description="The 6-digit code shown on the player's screen")
    name: str | None = Field(default=None, description="Name for the host; defaults to the player's own name")


class DiscoveredPlayerSchema(Schema):
    id: str
    name: str
    base_url: str
    version: str = ""
    paired: bool = Field(description="Whether the player is paired (with this or another Cinefin)")
    host_id: int | None = Field(None, description="The playout host this player already is, if any")


class DiscoveredPlayerListResponse(SuccessResponseSchema):
    data: list[DiscoveredPlayerSchema]


AGENT_DEFAULT_PORT = 8089


def _agent_url(raw: str) -> str:
    """Normalise a typed player address: add http:// and the default port when missing."""
    url = (raw or "").strip().rstrip("/")
    if not url:
        raise ValidationError("Enter the player's address", details={"field": "base_url"})
    if not re.match(r"^https?://", url):
        url = "http://" + url
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValidationError("That is not an address", details={"field": "base_url"})
    if parsed.port is None:
        url = f"{parsed.scheme}://{parsed.netloc}:{AGENT_DEFAULT_PORT}{parsed.path}"
    return url.rstrip("/")


def _host_or_404(host_id: int, error_code: str | None = "HOST_NOT_FOUND") -> PlayoutHost:
    host = PlayoutHost.objects.filter(pk=host_id).first()
    if host is None:
        raise NotFoundError("Playout host not found", error_code=error_code)
    return host


def _host_schema(host: PlayoutHost) -> PlayoutHostSchema:
    agent = host.kind == PlayoutHost.KIND_AGENT
    return PlayoutHostSchema(
        id=host.id,
        name=host.name,
        kind=host.kind,
        base_url=host.base_url,
        socket_path=host.socket_path or "",
        has_token=bool(host.token),
        agent_id=host.agent_id or "",
        needs_pairing_again=agent and bool(host.token) and not host.agent_id,
        needs_update=agent and bool(host.token) and host.protocol < PROTOCOL,
        needs_cinefin_update=agent and bool(host.token) and host.min_protocol > PROTOCOL,
        show_status=host.show_status,
        enabled=host.enabled,
        is_active=host.is_active,
        last_seen_at=host.last_seen_at.isoformat() if host.last_seen_at else None,
        agent_version=host.agent_version or "",
        os=host.os or "",
        arch=host.arch or "",
    )


@playout_api.get("/hosts", response={200: PlayoutHostListResponse})
def list_playout_hosts(request: HttpRequest):
    return Status(
        200, PlayoutHostListResponse(message="Playout hosts", data=[_host_schema(h) for h in PlayoutHost.objects.all()])
    )


@playout_api.get("/discover", response={200: DiscoveredPlayerListResponse})
def discover_players(request: HttpRequest):
    """Players announcing themselves on the local network (takes a couple of seconds)."""
    players = playout_discovery.discover()
    return Status(
        200,
        DiscoveredPlayerListResponse(
            message=f"{len(players)} player(s) found", data=[DiscoveredPlayerSchema(**vars(p)) for p in players]
        ),
    )


@playout_api.post(
    "/hosts/pair",
    response={200: PlayoutHostResponse, 400: ErrorResponseSchema, 409: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def pair_playout_host(request: HttpRequest, data: PairHostInput):
    """Pair a player with the code on its screen, adding it as a host (or re-pairing a known one)."""
    base_url = _agent_url(data.base_url)
    code = "".join(ch for ch in (data.code or "") if ch.isdigit())
    if len(code) != 6:
        raise ValidationError("Enter the 6-digit code shown on the player's screen", details={"field": "code"})
    answer = playout_agent_service.pair(base_url, code)

    agent_id = str(answer.get("id") or "")
    host = None
    if agent_id:
        host = PlayoutHost.objects.filter(kind=PlayoutHost.KIND_AGENT, agent_id=agent_id).first()
    if host is None:
        host = PlayoutHost.objects.filter(kind=PlayoutHost.KIND_AGENT, base_url=base_url).first()
    if host is None:
        host = PlayoutHost(kind=PlayoutHost.KIND_AGENT)
    name = (data.name or "").strip()
    if name or not host.name:
        host.name = name or str(answer.get("name") or "") or "Player"
    host.base_url = base_url
    host.token = answer["token"]
    host.agent_id = agent_id
    host.enabled = True
    host.agent_version = str(answer.get("agent_version") or "")
    host.os = str(answer.get("os") or "")
    host.arch = str(answer.get("arch") or "")
    host.protocol = int(answer.get("protocol") or 0)
    host.min_protocol = int(answer.get("min_protocol") or 0)
    host.last_seen_at = timezone.now()
    # The first player (or a re-paired active one) becomes the active host.
    activate = host.is_active or PlayoutHost.get_active() is None
    host.is_active = activate
    host.save()
    standby.forget(host.id)
    standby.push([host.id])
    if activate:
        playout_link.nudge()
    return Status(200, PlayoutHostResponse(message=f"Paired with {host.name}", data=_host_schema(host)))


@playout_api.post("/hosts", response={200: PlayoutHostResponse, 400: ErrorResponseSchema})
def create_playout_host(request: HttpRequest, data: PlayoutHostInput):
    name = (data.name or "").strip()
    kind = (data.kind or PlayoutHost.KIND_AGENT).strip()
    if kind not in {PlayoutHost.KIND_AGENT, PlayoutHost.KIND_LOCAL_SOCKET}:
        raise ValidationError("Unknown host kind", details={"field": "kind"})
    base_url = (data.base_url or "").strip()
    socket_path = (data.socket_path or "").strip()
    if not name:
        raise ValidationError("Name is required", details={"field": "name"})
    if kind == PlayoutHost.KIND_AGENT:
        raise ValidationError(
            "Playout agents are added by pairing (POST /playout/hosts/pair) with the code on the player's screen",
            error_code="PAIR_REQUIRED",
            details={"field": "kind"},
        )
    if not socket_path:
        raise ValidationError("A local mpv host needs a socket path", details={"field": "socket_path"})
    # Activate the new host when nothing is active yet — covers a fresh box
    # (whose seeded loopback host is inactive) so playout works immediately.
    activate = bool(data.is_active) or PlayoutHost.get_active() is None
    host = PlayoutHost.objects.create(
        name=name,
        kind=kind,
        base_url=base_url or PlayoutHost._meta.get_field("base_url").default,
        socket_path=socket_path,
        enabled=data.enabled if data.enabled is not None else True,
        is_active=activate,
    )
    if activate:
        standby.push([host.id])  # a local mpv goes to standby
    return Status(200, PlayoutHostResponse(message="Playout host added", data=_host_schema(host)))


@playout_api.patch(
    "/hosts/{host_id}", response={200: PlayoutHostResponse, 400: ErrorResponseSchema, 404: ErrorResponseSchema}
)
def update_playout_host(request: HttpRequest, host_id: int, data: PlayoutHostInput):
    host = _host_or_404(host_id, error_code=None)
    before = (host.name, host.show_status)
    if data.name is not None:
        host.name = data.name.strip() or host.name
    if data.show_status is not None:
        host.show_status = data.show_status
    if data.kind is not None:
        if data.kind not in {PlayoutHost.KIND_AGENT, PlayoutHost.KIND_LOCAL_SOCKET}:
            raise ValidationError("Unknown host kind", details={"field": "kind"})
        host.kind = data.kind
    if data.base_url is not None:
        base_url = data.base_url.strip()
        if base_url and not re.match(r"^https?://", base_url):
            raise ValidationError("Agent URL must start with http:// or https://", details={"field": "base_url"})
        host.base_url = base_url
    if data.socket_path is not None:
        host.socket_path = data.socket_path.strip()
    if data.enabled is not None:
        host.enabled = data.enabled
    if data.is_active:
        host.is_active = True  # save() clears the flag on the others
    # A local mpv host needs a socket path to be usable.
    if host.kind == PlayoutHost.KIND_LOCAL_SOCKET and not (host.socket_path or "").strip():
        raise ValidationError("A local mpv host needs a socket path", details={"field": "socket_path"})
    host.save()
    if (host.name, host.show_status) != before:
        standby.push([host.id])  # the player's name and show_status are in its spec
    return Status(200, PlayoutHostResponse(message="Playout host updated", data=_host_schema(host)))


@playout_api.post("/hosts/{host_id}/activate", response={200: PlayoutHostResponse, 404: ErrorResponseSchema})
def activate_playout_host(request: HttpRequest, host_id: int):
    host = _host_or_404(host_id, error_code=None)
    # Switching hosts: unload the programme (it belongs to the old host's player)
    # and drop the control link, while the controller still points at the old host.
    current = PlayoutHost.get_active()
    if current is not None and current.id != host.id:
        mpv_service.unload_for_host_switch()
    host.is_active = True
    host.save()
    standby.push([host.id])
    playout_link.nudge()
    return Status(200, PlayoutHostResponse(message="Playout host activated", data=_host_schema(host)))


@playout_api.post("/hosts/{host_id}/refresh", response={200: PlayoutHostResponse, 404: ErrorResponseSchema})
def refresh_playout_host(request: HttpRequest, host_id: int):
    host = _host_or_404(host_id, error_code=None)
    playout_host_service.refresh(host)
    host.refresh_from_db()
    return Status(200, PlayoutHostResponse(message="Playout host refreshed", data=_host_schema(host)))


@playout_api.delete("/hosts/{host_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema})
def delete_playout_host(request: HttpRequest, host_id: int):
    host = _host_or_404(host_id, error_code=None)
    was_active = host.is_active
    name = host.name
    if was_active:
        # Stop what is on air and drop the control link while it still points here.
        mpv_service.unload_for_host_switch()
    # The player forgets this Cinefin and shows a pairing code again (best effort:
    # a player that is off still gets removed here).
    playout_agent_service.unpair(host)
    host.delete()
    if was_active:
        nxt = PlayoutHost.objects.first()
        if nxt:
            nxt.is_active = True
            nxt.save()
        playout_link.nudge()
    return Status(200, MessageResponseSchema(message=f"Playout host '{name}' removed"))


# Host-owned graphics/audio config: addressed per host (belongs to the machine),
# validated + persisted by the agent (its own copy is what it boots from).
@playout_api.get(
    "/hosts/{host_id}/config",
    response={200: HostLaunchConfigResponse, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def get_host_launch_config(request: HttpRequest, host_id: int):
    """One host's launch config (autostart, graphics, audio), read from that machine's agent."""
    data = playout_agent_service.get_host_config(_host_or_404(host_id))
    return Status(200, HostLaunchConfigResponse(message="Host launch config", data=data))


@playout_api.put(
    "/hosts/{host_id}/config",
    response={200: HostConfigSavedResponse, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def put_host_launch_config(request: HttpRequest, host_id: int, body: HostLaunchConfigSchema):
    """Replace one host's launch config; the agent validates and stores it (applies on next restart)."""
    host = _host_or_404(host_id)
    saved = playout_agent_service.put_host_config(host, body.dict())
    return Status(200, HostConfigSavedResponse(message="Host config saved", data=saved))


@playout_api.get(
    "/hosts/{host_id}/hardware",
    response={200: HostHardwareResponse, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def get_host_hardware(request: HttpRequest, host_id: int):
    """What one host actually has (audio devices, DRM connectors, screens, mpv caps), enumerated on demand."""
    data = playout_agent_service.get_hardware(_host_or_404(host_id))
    return Status(200, HostHardwareResponse(message="Host hardware", data=data))


class TestCardInput(Schema):
    on: bool = Field(description="Show (true) or hide (false) the test card")


class TestCardSchema(Schema):
    on: bool
    off_in_s: int = 0


class TestCardResponse(SuccessResponseSchema):
    data: TestCardSchema


class TestSoundStepSchema(Schema):
    channel: Literal["left", "right"]
    start_ms: int
    duration_ms: int


class TestSoundSchema(Schema):
    playing: bool = True
    frequency_hz: int = 0
    duration_ms: int = 0
    sequence: list[TestSoundStepSchema] = Field(default_factory=list, description="Which side sounds when")


class TestSoundResponse(SuccessResponseSchema):
    data: TestSoundSchema


@playout_api.post(
    "/hosts/{host_id}/testcard",
    response={200: TestCardResponse, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def host_test_card(request: HttpRequest, host_id: int, data: TestCardInput):
    """Show or hide the player's test card: its name, output and speaker boxes, over standby."""
    answer = playout_agent_service.test_card(_host_or_404(host_id), data.on)
    return Status(200, TestCardResponse(message="Test card on" if data.on else "Test card off", data=answer))


@playout_api.post(
    "/hosts/{host_id}/testsound",
    response={200: TestSoundResponse, 404: ErrorResponseSchema, 409: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def host_test_sound(request: HttpRequest, host_id: int):
    """Play the player's test sound, left then right. 409 while one plays or when the player is not on standby."""
    answer = playout_agent_service.test_sound(_host_or_404(host_id))
    return Status(200, TestSoundResponse(message="Test sound playing", data=answer))


@playout_api.post(
    "/hosts/{host_id}/restart",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def restart_host(request: HttpRequest, host_id: int):
    """Restart one player's mpv, so a changed launch config applies."""
    host = _host_or_404(host_id)
    playout_agent_service.restart_host(host)
    return Status(200, MessageResponseSchema(message=f"{host.name} is restarting"))
