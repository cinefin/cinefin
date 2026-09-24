from django.core.validators import MinValueValidator
from django.db import models

from .automation import Command
from .media import Bumper, Certification, Movie, Trailer
from .programme import Programme


class Playlist(models.Model):
    programme = models.OneToOneField(Programme, on_delete=models.CASCADE, related_name="playlist")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Playlist for {self.programme.name}"


class PlaylistItem(models.Model):
    CONTENT_TYPES = (
        ("movie", "MoviePlayback"),
        ("bumper", "Bumper"),
        ("command", "Command"),
        ("certification", "Certification"),
        ("trailer", "Trailer"),
        ("system", "System"),
    )

    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES, blank=True)

    # At most one link set, selected by content_type. SET_NULL preserves the old GFK behaviour
    # (deleting the target leaves the item; playback uses `file`). "movie" points at a MoviePlayback wrapper.
    movie_playback = models.ForeignKey(
        "MoviePlayback", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    trailer = models.ForeignKey(Trailer, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    bumper = models.ForeignKey(Bumper, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    command = models.ForeignKey(Command, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    certification = models.ForeignKey(Certification, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="items")
    # null for pre-show/ident items
    programme_block = models.ForeignKey(
        "ProgrammeBlock", null=True, blank=True, on_delete=models.SET_NULL, related_name="playlist_items"
    )
    order = models.PositiveIntegerField()
    file = models.CharField(max_length=10000)
    # Generation-time facts not recomputable from the content link (e.g. trailer-rule match tier/reference movie).
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order"]

    @property
    def content_object(self):
        if self.content_type == "movie":
            return self.movie_playback
        if self.content_type == "trailer":
            return self.trailer
        if self.content_type == "bumper":
            return self.bumper
        if self.content_type == "command":
            return self.command
        if self.content_type == "certification":
            return self.certification
        return None

    def __str__(self):
        return f"{self.playlist} - Item {self.order}"


class PlaylistCue(models.Model):
    """Instant command cue: fires when playback reaches fires_before_order (forward jumps fire every cue passed, backward fire none)."""

    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="cues")
    command = models.ForeignKey(Command, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # Snapshot for logs/UI if the command is later deleted
    command_name = models.CharField(max_length=255, blank=True, default="")
    fires_before_order = models.PositiveIntegerField()
    seq = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["fires_before_order", "seq"]

    def __str__(self):
        return f"Cue '{self.command_name}' before item {self.fires_before_order}"


class MoviePlayback(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    audio_track_index = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    subtitle_track_index = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    credits_command = models.ForeignKey(
        Command,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movie_playback_credits",
        help_text="Command to execute when credits begin",
    )

    def __str__(self):
        return f"{self.movie.title} - Playback"


class PlayoutHost(models.Model):
    # Two transports by kind: `agent` (remote agent over WebSocket, owns process + config) and
    # `local_socket` (operator-run mpv unix socket). Exactly one row is_active, enforced in save().
    KIND_AGENT = "agent"
    KIND_LOCAL_SOCKET = "local_socket"
    KIND_CHOICES = [
        (KIND_AGENT, "Playout agent (WebSocket)"),
        (KIND_LOCAL_SOCKET, "Local mpv (JSON-IPC socket)"),
    ]

    name = models.CharField(max_length=255, help_text="Friendly name for the playout host")
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default=KIND_AGENT,
        help_text="Transport: remote agent (WebSocket) or a local mpv JSON-IPC socket",
    )
    base_url = models.CharField(
        max_length=500,
        default="http://127.0.0.1:8089",
        help_text="Agent HTTP base URL, e.g. http://127.0.0.1:8089 (agent kind only)",
    )
    socket_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="mpv --input-ipc-server path, e.g. /tmp/mpvsocket (local_socket kind only)",
    )
    token = models.CharField(max_length=500, blank=True, default="", help_text="Bearer token for the agent")
    enabled = models.BooleanField(default=True, help_text="Whether this host may be used for playout")
    is_active = models.BooleanField(
        default=False, help_text="The single host used for playout (exactly one row is active)"
    )

    # Populated by PlayoutHostService.refresh() from the agent's /status + /health.
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="Last successful agent contact")
    agent_version = models.CharField(max_length=100, blank=True, default="")
    os = models.CharField(max_length=50, blank=True, default="")
    arch = models.CharField(max_length=50, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        marker = " (active)" if self.is_active else ""
        target = self.socket_path if self.kind == self.KIND_LOCAL_SOCKET else self.base_url
        return f"{self.name} @ {target}{marker}"

    def save(self, *args, **kwargs):
        # Exactly one active host: setting this one active clears the others.
        if self.is_active:
            PlayoutHost.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls) -> "PlayoutHost | None":
        return cls.objects.filter(is_active=True).first()


class PlayoutSession(models.Model):
    """Singleton persisting mpv_service lifecycle so a fresh process can re-attach to a screening still on air across restarts."""

    programme = models.ForeignKey(Programme, null=True, blank=True, on_delete=models.SET_NULL)
    state = models.CharField(max_length=20, default="not_loaded")
    playlist_offset = models.PositiveIntegerField(default=0)
    # Last programme item order reached (drives command cue firing; -1 = pre-show)
    programme_cursor = models.IntegerField(default=-1)
    # PlaylistItem ids whose credits command already fired (avoid re-firing after re-attach)
    credits_executed = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls) -> "PlayoutSession":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"PlayoutSession({self.state}, programme={self.programme_id})"
