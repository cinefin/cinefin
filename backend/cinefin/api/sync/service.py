"""SyncManager — source CRUD, job enqueue/cancel, history.

A library has ONE source (Plex or Jellyfin, not both): both plugins match on
tmdbid globally, so two sources would race and silently overwrite each other's
file path/resolution/tracks. `create_source` refuses a second; ask via `the_source()`.
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from cinefin.api.exceptions import ConflictError, NotFoundError, ValidationError
from cinefin.api.models import Job, SyncSource

from . import registry

logger = logging.getLogger("cinefin.sync")

# Sentinels the UI sends back for an unchanged secret; never persist these.
_TOKEN_PLACEHOLDERS = {"", "***", "********"}


def _clean_path_mappings(raw) -> list[dict[str, str]]:
    cleaned = []
    for rule in raw or []:
        if not isinstance(rule, dict):
            continue
        src = str(rule.get("from") or "").strip()
        dst = str(rule.get("to") or "").strip()
        if src and dst:
            cleaned.append({"from": src, "to": dst})
    return cleaned


class SyncManager:
    @staticmethod
    def get_source(source_id: int) -> SyncSource:
        try:
            return SyncSource.objects.get(pk=source_id)
        except SyncSource.DoesNotExist:
            raise NotFoundError("Sync source not found", error_code="SYNC_SOURCE_NOT_FOUND") from None

    @classmethod
    def list_sources(cls) -> list[dict[str, Any]]:
        return [cls.serialize_source(s) for s in SyncSource.objects.all()]

    @staticmethod
    def the_source() -> SyncSource | None:
        """The library's one source, or None. Ask via this, not scattered `.first()`."""
        return SyncSource.objects.order_by("id").first()

    @classmethod
    def create_source(cls, data: dict[str, Any]) -> SyncSource:
        existing = cls.the_source()
        if existing is not None:
            raise ConflictError(
                f"A library source is already configured ({existing.name}). "
                "Remove it before adding a different server.",
                error_code="SYNC_SOURCE_EXISTS",
            )

        sync_type = data.get("sync_type")
        if registry.get_plugin_class(sync_type) is None:
            raise ValidationError(f"Invalid sync type: {sync_type}", error_code="INVALID_SYNC_TYPE")
        if not data.get("name"):
            raise ValidationError("Name is required", error_code="MISSING_NAME")

        token = data.get("token")
        if not data.get("url") or not token or token in _TOKEN_PLACEHOLDERS:
            raise ValidationError("URL and token are required", error_code="MISSING_REQUIRED_FIELDS")
        return SyncSource.objects.create(
            name=data["name"],
            sync_type=sync_type,
            url=data["url"].rstrip("/"),
            token=token,
            libraries=data.get("libraries", "Films,Documentaries"),
            enabled=data.get("enabled", True),
            extra_config=data.get("extra_config", {}),
            path_mappings=_clean_path_mappings(data.get("path_mappings")),
        )

    @classmethod
    def update_source(cls, source_id: int, data: dict[str, Any]) -> SyncSource:
        source = cls.get_source(source_id)
        if cls.has_active_job(source):
            raise ValidationError("Cannot edit a source while it is syncing", error_code="SYNC_IN_PROGRESS")

        if "name" in data:
            source.name = data["name"]
        if "enabled" in data:
            source.enabled = data["enabled"]

        # Overwrite the secret only for a real value (UI sends '***' = keep existing).
        token = data.get("token")
        keep_token = token is None or token in _TOKEN_PLACEHOLDERS

        if "url" in data:
            source.url = data["url"].rstrip("/")
        if not keep_token:
            source.token = token
        if "libraries" in data:
            source.libraries = data["libraries"]
        if "extra_config" in data:
            source.extra_config = data["extra_config"]
        if "path_mappings" in data:
            source.path_mappings = _clean_path_mappings(data["path_mappings"])

        source.save()
        return source

    @classmethod
    def delete_source(cls, source_id: int, delete_movies: bool = False) -> int:
        """Remove a source. With delete_movies, also delete the films it synced (otherwise
        they stay, orphaned via SET_NULL). Returns how many movies were deleted."""
        source = cls.get_source(source_id)
        if cls.has_active_job(source):
            raise ValidationError("Cannot delete a source while it is syncing", error_code="SYNC_IN_PROGRESS")
        movies_deleted = 0
        if delete_movies:
            from cinefin.api.models import Movie

            qs = Movie.objects.filter(sync_source=source)
            movies_deleted = qs.count()
            qs.delete()
        source.delete()
        return movies_deleted

    @classmethod
    def test_connection(cls, source_id: int) -> dict[str, Any]:
        source = cls.get_source(source_id)
        plugin = registry.get_plugin(source)
        if plugin is None:
            raise ValidationError("No plugin for this source type", error_code="NO_PLUGIN")
        ok, message = plugin.test_connection()
        libraries = plugin.get_libraries() if ok else []
        return {"success": ok, "message": message, "libraries": libraries}

    @classmethod
    def probe(
        cls,
        sync_type: str,
        url: str,
        token: str | None,
        source_id: int | None = None,
    ) -> dict[str, Any]:
        """Test an un-saved connection and list its server-side libraries.

        Used by the Add/Edit form so the operator picks from the real library
        names instead of typing them. When editing (`source_id` given) a blank
        token means "keep the saved one".
        """
        plugin_cls = registry.get_plugin_class(sync_type)
        if plugin_cls is None:
            raise ValidationError(f"Invalid sync type: {sync_type}", error_code="INVALID_SYNC_TYPE")

        token = (token or "").strip()
        if token in _TOKEN_PLACEHOLDERS and source_id is not None:
            token = cls.get_source(source_id).token
        if not url or not token:
            raise ValidationError("URL and token are required", error_code="MISSING_REQUIRED_FIELDS")

        probe_source = SyncSource(sync_type=sync_type, url=url.rstrip("/"), token=token, libraries="")
        plugin = plugin_cls(probe_source)
        ok, message = plugin.test_connection()
        libraries = plugin.get_libraries() if ok else []
        return {"success": ok, "message": message, "libraries": libraries}

    @staticmethod
    def has_active_job(source: SyncSource) -> bool:
        return Job.sync.filter(source=source, state__in=Job.ACTIVE_STATES).exists()

    @classmethod
    def enqueue(
        cls,
        source_id: int,
        operation: str | None = None,
        params: dict[str, Any] | None = None,
        max_attempts: int = 1,
    ) -> Job:
        source = cls.get_source(source_id)
        if not source.enabled:
            raise ValidationError("Sync source is disabled", error_code="SOURCE_DISABLED")

        plugin_cls = registry.get_plugin_class(source.sync_type)
        if plugin_cls is None:
            raise ValidationError("No plugin for this source type", error_code="NO_PLUGIN")

        operation = operation or plugin_cls.operations[0]
        if operation not in plugin_cls.operations:
            raise ValidationError(
                f"Operation '{operation}' not supported by {source.sync_type}", error_code="INVALID_OPERATION"
            )
        if cls.has_active_job(source):
            raise ValidationError("A sync is already queued or running for this source", error_code="SYNC_IN_PROGRESS")

        job = Job.sync.create(
            source=source,
            operation=operation,
            params=params or {},
            max_attempts=max(1, max_attempts),
        )
        logger.info("Enqueued job #%s (%s:%s)", job.pk, source.name, operation)
        return job

    @classmethod
    def cancel_active(cls, source_id: int) -> Job:
        source = cls.get_source(source_id)
        job = Job.sync.filter(source=source, state__in=Job.ACTIVE_STATES).order_by("-created_at").first()
        if job is None:
            raise ValidationError("No sync in progress", error_code="NO_SYNC_IN_PROGRESS")
        if job.state == Job.STATE_QUEUED:
            # Not started yet — cancel outright.
            Job.sync.filter(pk=job.pk, state=Job.STATE_QUEUED).update(
                state=Job.STATE_CANCELLED, finished_at=timezone.now(), phase="Cancelled before start"
            )
        else:
            Job.sync.filter(pk=job.pk).update(state=Job.STATE_CANCELLING, phase="Cancelling…")
        job.refresh_from_db()
        return job

    @classmethod
    def list_jobs(cls, source_id: int | None = None, limit: int = 50, active_only: bool = False) -> list[Job]:
        qs = Job.sync.all()
        if source_id is not None:
            qs = qs.filter(source_id=source_id)
        if active_only:
            qs = qs.filter(state__in=Job.ACTIVE_STATES)
        return list(qs[:limit])

    @classmethod
    def get_job(cls, job_id: int) -> Job:
        try:
            return Job.sync.get(pk=job_id)
        except Job.DoesNotExist:
            raise NotFoundError("Sync job not found", error_code="SYNC_JOB_NOT_FOUND") from None

    @classmethod
    def serialize_source(cls, source: SyncSource) -> dict[str, Any]:
        active = Job.sync.filter(source=source, state__in=Job.ACTIVE_STATES).order_by("-created_at").first()
        last = Job.sync.filter(source=source, state__in=Job.TERMINAL_STATES).order_by("-created_at").first()

        data = {
            "id": source.id,
            "name": source.name,
            "sync_type": source.sync_type,
            "url": source.url,
            "token_set": bool(source.token),
            "libraries": source.libraries,
            "path_mappings": source.path_mappings or [],
            "enabled": source.enabled,
            "movie_count": source.movies.count(),
            "last_sync": source.last_sync.isoformat() if source.last_sync else None,
            "is_syncing": bool(active),
            "active_job": cls.serialize_job(active, brief=True) if active else None,
            "last_job": cls.serialize_job(last, brief=True) if last else None,
            "created_at": source.created_at.isoformat(),
            "updated_at": source.updated_at.isoformat(),
        }
        return data

    @classmethod
    def serialize_job(cls, job: Job | None, brief: bool = False, include_log: bool = False) -> dict[str, Any] | None:
        if job is None:
            return None
        return job.serialize(brief=brief, include_log=include_log)
