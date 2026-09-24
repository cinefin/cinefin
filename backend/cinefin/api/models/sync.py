"""Sync system models: sources and DB-persisted job rows."""

from django.db import models
from django.utils import timezone


class SyncSource(models.Model):
    SYNC_TYPES = [
        ("plex", "Plex Media Server"),
        ("jellyfin", "Jellyfin"),
    ]

    name = models.CharField(max_length=100, unique=True)
    sync_type = models.CharField(max_length=20, choices=SYNC_TYPES)
    url = models.CharField(max_length=500, help_text="Server URL (e.g. http://192.0.2.10:32400)")
    token = models.CharField(max_length=500, help_text="API token or authentication key")
    libraries = models.TextField(
        help_text="Comma-separated list of library names to sync", default="Films,Documentaries"
    )
    enabled = models.BooleanField(default=True)
    last_sync = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    extra_config = models.JSONField(
        default=dict, blank=True, help_text="Additional configuration specific to sync type"
    )

    # Rewrites for server-reported paths (mismatched mounts); longest prefix wins.
    path_mappings = models.JSONField(
        default=list, blank=True, help_text='Path rewrites: [{"from": "/server/path", "to": "/local/path"}]'
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Sync Source"
        verbose_name_plural = "Sync Sources"

    def __str__(self):
        return f"{self.name} ({self.get_sync_type_display()})"

    def get_libraries_list(self):
        return [lib.strip() for lib in self.libraries.split(",") if lib.strip()]


class JobKindManager(models.Manager):
    """Scoped to one job kind; `create()` stamps the kind automatically."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind

    def get_queryset(self):
        return super().get_queryset().filter(kind=self.kind)

    def create(self, **kwargs):
        kwargs.setdefault("kind", self.kind)
        return super().create(**kwargs)


class Job(models.Model):
    """DB-persisted background job (queue entry + run record). Two kinds share
    this table (query via Job.sync / Job.trailer): sync jobs use source and the
    retry-queue fields and cancel via state="cancelling"; trailer jobs have no
    source/retry and cancel via cancel_requested."""

    KIND_SYNC = "sync"
    KIND_TRAILER = "trailer"
    KINDS = [
        (KIND_SYNC, "Sync"),
        (KIND_TRAILER, "Trailer"),
    ]

    STATE_QUEUED = "queued"
    STATE_RUNNING = "running"
    STATE_CANCELLING = "cancelling"
    STATE_SUCCESS = "success"
    STATE_PARTIAL = "partial"
    STATE_FAILED = "failed"
    STATE_CANCELLED = "cancelled"
    STATES = [
        (STATE_QUEUED, "Queued"),
        (STATE_RUNNING, "Running"),
        (STATE_CANCELLING, "Cancelling"),
        (STATE_SUCCESS, "Success"),
        (STATE_PARTIAL, "Partial"),
        (STATE_FAILED, "Failed"),
        (STATE_CANCELLED, "Cancelled"),
    ]
    ACTIVE_STATES = (STATE_QUEUED, STATE_RUNNING, STATE_CANCELLING)
    TERMINAL_STATES = (STATE_SUCCESS, STATE_PARTIAL, STATE_FAILED, STATE_CANCELLED)

    kind = models.CharField(max_length=20, choices=KINDS, db_index=True)
    # sync jobs only — trailer jobs have no source.
    source = models.ForeignKey(SyncSource, on_delete=models.CASCADE, null=True, blank=True, related_name="jobs")

    operation = models.CharField(max_length=40, default="sync")
    params = models.JSONField(default=dict, blank=True)

    state = models.CharField(max_length=20, choices=STATES, default=STATE_QUEUED, db_index=True)
    # Queueing / retry fields — sync engine only; trailer jobs keep the defaults.
    priority = models.IntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=1)
    scheduled_for = models.DateTimeField(default=timezone.now, db_index=True)
    worker = models.CharField(max_length=80, blank=True, default="")
    cancel_requested = models.BooleanField(default=False)  # trailer cancel channel

    phase = models.CharField(max_length=160, blank=True, default="")
    current = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    current_item = models.CharField(max_length=300, blank=True, default="")

    counts = models.JSONField(default=dict, blank=True)  # keys vary by kind
    error = models.TextField(blank=True, default="")
    log = models.JSONField(default=list, blank=True)  # [{ts, level, message}]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = models.Manager()
    sync = JobKindManager(KIND_SYNC)
    trailer = JobKindManager(KIND_TRAILER)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Job"
        verbose_name_plural = "Jobs"
        indexes = [
            models.Index(fields=["kind", "state", "scheduled_for"]),
            models.Index(fields=["source", "-created_at"]),
        ]

    def __str__(self):
        target = f"{self.source_id}:" if self.source_id else ""
        return f"#{self.pk} {self.kind} {target}{self.operation} [{self.state}]"

    @property
    def is_active(self):
        return self.state in self.ACTIVE_STATES

    @property
    def percentage(self):
        return round((self.current / self.total * 100), 1) if self.total > 0 else 0.0

    @property
    def duration_seconds(self):
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return (end - self.started_at).total_seconds()

    def serialize(self, *, brief: bool = False, include_log: bool = False) -> dict:
        data = {
            "id": self.id,
            "source_id": self.source_id,
            "operation": self.operation,
            "state": self.state,
            "is_active": self.is_active,
            "phase": self.phase,
            "current": self.current,
            "total": self.total,
            "percentage": self.percentage,
            "current_item": self.current_item,
            "counts": self.counts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds,
        }
        if not brief:
            data["params"] = self.params
            data["error"] = self.error
            data["attempts"] = self.attempts
            data["max_attempts"] = self.max_attempts
        if include_log:
            data["log"] = self.log or []
        return data
