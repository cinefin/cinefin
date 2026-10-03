"""The playout status: one schema for GET /playout/status and the WebSocket push.

Both are readable without a session when kiosks are public (auth_service.KIOSK_PUBLIC_PATHS and
the WebSocket's public "playout" channel), so nothing here may carry an address, a token, a
socket path or a stream URL (they carry tokens)."""

from datetime import datetime
from typing import Any, Literal

from ninja import Field, Schema

Phase = Literal["offline", "standby", "cued", "preshow", "playing", "paused", "hold", "manual"]
Action = Literal[
    "cue", "start", "pause", "resume", "previous", "next", "seek", "jump", "end_hold", "end", "recover", "dismiss"
]


class ProgrammeFeatureSchema(Schema):
    id: int
    title: str
    year: int | None = None
    certification: str | None = Field(None, description="Certificate for the active ratings system")
    runtime_minutes: int | None = None
    thumbnail_url: str | None = None


class ProgrammeInfoSchema(Schema):
    id: int
    name: str
    description: str
    runtime_minutes: int
    runtime_formatted: str
    block_count: int
    created_at: str | None = None
    features: list[ProgrammeFeatureSchema] = Field(
        default_factory=list, description="The programme's feature films, in running order"
    )


class PlaylistStatusSchema(Schema):
    current_position: int | None = Field(None, description="Programme position on screen (None before the first item)")
    total_items: int = Field(..., description="Items in the running order (the end sentinel not counted)")
    mpv_position: int | None = Field(None, description="The player's playlist index")
    offset: int = Field(..., description="Player index of programme item 0 (1, or 2 with a title card)")
    programme_total_duration: float
    programme_elapsed_time: float
    programme_remaining_time: float


class ItemSchema(Schema):
    type: str = Field(..., description="Item type (movie, trailer, title, ...)")
    position: int = Field(..., description="Programme position; -1 for the title card")
    title: str | None = None
    duration: float | None = Field(None, description="Length in seconds, when known")
    details: dict[str, Any] = Field(default_factory=dict, description="content_id and per-type metadata")


class PlaybackStatusSchema(Schema):
    position: float = Field(..., description="Seconds into the item on screen (a hold's own clock during a hold)")
    duration: float
    remaining: float
    percentage: float = Field(..., description="Progress through the item, 0 to 100")


class ManualItemSchema(Schema):
    title: str
    kind: str


class ManualQueueSchema(Schema):
    items: list[ManualItemSchema]
    position: int | None = None


class PlayerSchema(Schema):
    """The active player. Never its address, token or socket path: this status is public to
    kiosks (GET /playout/status and the WebSocket), and the address is in GET /playout/hosts."""

    id: int
    name: str
    kind: str = Field(..., description="'agent' or 'local_socket'")
    show_status: bool = Field(..., description="Whether the player shows its status line over standby")


class NextScreeningSchema(Schema):
    id: int
    programme_id: int
    programme_name: str
    start_time: datetime
    cue_time: datetime = Field(..., description="When its lead-in cues it")


class InterruptedSchema(Schema):
    """A programme the player lost while on air (it restarted), for the operator to resume."""

    programme_id: int
    programme_name: str
    position: int = Field(..., description="Programme position of the item it was on")
    item_title: str | None = None
    seconds: float | None = Field(None, description="How far into that item, when known")


class PlayoutStatusDataSchema(Schema):
    phase: Phase = Field(..., description="What the player is doing, worked out once for every surface")
    screen: str = Field("", description="What the audience sees, e.g. 'System Ident', 'Title card', 'Alien'")
    label: str = Field("", description="One line for the phase, e.g. 'Cued · Friday Night: Alien'")
    actions: list[Action] = Field(default_factory=list)
    player: PlayerSchema | None = Field(None, description="The active player, if one is set up")
    next_screening: NextScreeningSchema | None = None
    programme: ProgrammeInfoSchema | None = None
    playlist: PlaylistStatusSchema | None = None
    current_item: ItemSchema | None = Field(None, description="The item on screen (the title card in the pre-show)")
    next_item: ItemSchema | None = None
    playback: PlaybackStatusSchema | None = None
    manual: ManualQueueSchema | None = None
    interrupted: InterruptedSchema | None = Field(None, description="A programme the player lost, to resume")
