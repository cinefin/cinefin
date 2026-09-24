"""
Backup & restore for the whole deployment.

The entire Cinefin install is one SQLite database file (programmes, schedules,
settings, ticket history — everything) plus the application settings JSON, which
also lives in that database. Home installs die from lost databases far more often
than from bugs, so this module produces a one-click backup and a careful restore.

Scope: the DATABASE ONLY. The ``usermedia/`` tree (posters, generated cert/title
videos, uploaded media) is deliberately EXCLUDED — it is potentially large and is
re-derivable (posters stream live from Plex/Jellyfin, cert/title cards regenerate).

A backup is a ``.zip`` containing:

* ``db.sqlite3`` — a *consistent* copy of the live database, serialised from the
  live connection so a mid-write database is never copied.
* ``manifest.json`` — format version, app version, timestamp and the latest
  applied migration name, so restore can refuse an incompatible backup.

Restore never touches the live database until the uploaded one has been fully
validated (zip opens, manifest parses, format understood, migration state not
ahead of this code, and the uploaded DB passes ``PRAGMA integrity_check`` in a
temp location). Only then is the live file replaced atomically with ``os.replace``.
The running process is NOT hot-swapped — the caller is told a restart is required
(home deploys restart via ``git pull`` / systemd / docker).
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from cinefin.api.exceptions import ValidationError
from cinefin.version import get_version

# Bump when the archive layout changes in a way older code can't read. Restore
# refuses any archive whose format version is newer than this.
BACKUP_FORMAT_VERSION = 1

# Names inside the archive.
DB_ARCNAME = "db.sqlite3"
MANIFEST_ARCNAME = "manifest.json"

# Multipart field name the restore endpoint (and the JS client) uses.
RESTORE_FIELD_NAME = "backup"

# SQLite database files start with this 16-byte header string.
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _db_path() -> Path:
    """Absolute path of the live SQLite database, resolved at runtime.

    Never hardcode — Docker overrides the location via ``SQLITE_PATH`` and the
    test suite runs against its own database.
    """
    return Path(connection.settings_dict["NAME"])


def _latest_migration() -> str | None:
    """Name of the most recently applied migration for the ``api`` app.

    Migrations apply in order, so the last one recorded is the schema high-water
    mark. Used by restore to refuse a backup whose schema is ahead of this code.
    """
    applied = MigrationRecorder.Migration.objects.filter(app="api").order_by("id").values_list("name", flat=True)
    names = list(applied)
    return names[-1] if names else None


def _known_migrations() -> set[str]:
    """Every ``api`` migration this code knows about (recorded as applied)."""
    return set(MigrationRecorder.Migration.objects.filter(app="api").values_list("name", flat=True))


def _timestamp() -> datetime:
    return datetime.now(UTC)


def build_manifest() -> dict:
    """The manifest embedded in a backup and echoed back by validation."""
    return {
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": get_version(),
        "created_at": _timestamp().isoformat(),
        "latest_migration": _latest_migration(),
        "database_filename": DB_ARCNAME,
        "includes_media": False,
    }


def backup_filename(when: datetime | None = None) -> str:
    """``cinefin-backup-<YYYYMMDD-HHMMSS>-<version>.zip`` (filesystem-safe)."""
    when = when or _timestamp()
    stamp = when.strftime("%Y%m%d-%H%M%S")
    version = get_version().replace("/", "-").replace(" ", "-")
    return f"cinefin-backup-{stamp}-{version}.zip"


def _snapshot_db(dest: Path) -> None:
    """Write a consistent snapshot of the live DB to ``dest``.

    Serialises Django's live SQLite connection with ``iterdump()`` and replays
    it into a fresh database file. ``iterdump()`` reads the current state through
    the existing connection, so it captures a consistent view of a database that
    may be mid-write, works for both file-backed and in-memory databases, and —
    unlike ``VACUUM INTO`` or the online backup API — doesn't block or fail when
    a transaction is already open on the connection (Django's test runner wraps
    each test in one).
    """
    connection.ensure_connection()
    source = connection.connection  # underlying sqlite3.Connection
    dest_conn = sqlite3.connect(str(dest))
    try:
        dest_conn.executescript("".join(source.iterdump()))
        dest_conn.commit()
    finally:
        dest_conn.close()


def create_backup(dest_path: str | os.PathLike) -> Path:
    """Write a complete backup zip to ``dest_path`` and return its Path.

    The DB snapshot is serialised from the live connection via iterdump() (see
    _snapshot_db — deliberately not the online backup API, which blocks/fails on
    an open transaction), added to the archive, then removed. The archive is
    written to a sibling temp file and
    atomically renamed into place so a partially-written zip is never left behind.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest()

    tmp_db = Path(tempfile.mkstemp(prefix="cinefin-db-", suffix=".sqlite3")[1])
    tmp_zip = Path(tempfile.mkstemp(prefix="cinefin-backup-", suffix=".zip", dir=dest_path.parent)[1])
    try:
        _snapshot_db(tmp_db)

        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_ARCNAME, json.dumps(manifest, indent=2))
            zf.write(tmp_db, arcname=DB_ARCNAME)

        os.replace(tmp_zip, dest_path)
        return dest_path
    finally:
        tmp_db.unlink(missing_ok=True)
        # If os.replace succeeded, tmp_zip is already gone; clean up on failure.
        Path(tmp_zip).unlink(missing_ok=True)


def get_info() -> dict:
    """Readout for the Settings page: size, filename, last-modified, version.

    Only the database *filename* is exposed, never the absolute host path.
    """
    path = _db_path()
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat() if exists else None
    return {
        "database_filename": path.name,
        "database_size_bytes": size,
        "database_modified_at": modified,
        "app_version": get_version(),
        "latest_migration": _latest_migration(),
        "includes_media": False,
        "format_version": BACKUP_FORMAT_VERSION,
    }


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    """Parse and shallow-validate the manifest from an open archive."""
    try:
        raw = zf.read(MANIFEST_ARCNAME)
    except KeyError:
        raise ValidationError(
            "This file isn't a Cinefin backup — its manifest is missing.",
            error_code="BACKUP_MANIFEST_MISSING",
        ) from None
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError(
            "The backup's manifest is corrupt and can't be read.",
            error_code="BACKUP_MANIFEST_INVALID",
        ) from None
    if not isinstance(manifest, dict) or "format_version" not in manifest:
        raise ValidationError(
            "The backup's manifest is missing required fields.",
            error_code="BACKUP_MANIFEST_INVALID",
        )
    return manifest


def _check_format_version(manifest: dict) -> None:
    fmt = manifest.get("format_version")
    if not isinstance(fmt, int):
        raise ValidationError(
            "The backup's format version is missing or invalid.",
            error_code="BACKUP_FORMAT_INVALID",
        )
    if fmt > BACKUP_FORMAT_VERSION:
        raise ValidationError(
            f"This backup was made by a newer version of Cinefin (backup format v{fmt}, "
            f"this install understands up to v{BACKUP_FORMAT_VERSION}). Update Cinefin, then restore.",
            error_code="BACKUP_FORMAT_TOO_NEW",
        )


def _check_migration_state(manifest: dict) -> None:
    """Refuse a backup whose schema is ahead of what this code can run.

    If the backup's latest migration isn't one this code knows about, restoring
    it would leave the DB schema newer than the running code — which breaks. The
    honest thing is to refuse and tell the user to update first. A backup that is
    *behind* is fine: Django's ``migrate`` rolls it forward on next start.
    """
    latest = manifest.get("latest_migration")
    if not latest:
        # A very old / empty backup with no recorded migrations — allow it;
        # migrate will bring it up to date.
        return
    if latest not in _known_migrations():
        raise ValidationError(
            f"This backup's database is newer than this install (its latest migration "
            f"'{latest}' isn't known here). Update Cinefin to at least the version that "
            f"created the backup, then restore.",
            error_code="BACKUP_MIGRATION_AHEAD",
        )


def _validate_sqlite_file(path: Path) -> None:
    """Header check + PRAGMA integrity_check on an uploaded DB in a temp location.

    Runs BEFORE the live database is touched. Raises ValidationError on any sign
    the file isn't a healthy SQLite database.
    """
    try:
        with open(path, "rb") as fh:
            header = fh.read(16)
    except OSError as e:
        raise ValidationError(
            f"The backup's database couldn't be read: {e}",
            error_code="BACKUP_DB_UNREADABLE",
        ) from e
    if header != _SQLITE_MAGIC:
        raise ValidationError(
            "The file inside the backup isn't a valid SQLite database.",
            error_code="BACKUP_DB_NOT_SQLITE",
        )
    try:
        conn = sqlite3.connect(str(path))
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise ValidationError(
            f"The backup's database failed its integrity check: {e}",
            error_code="BACKUP_DB_CORRUPT",
        ) from e
    if not result or result[0] != "ok":
        detail = result[0] if result else "unknown error"
        raise ValidationError(
            f"The backup's database failed its integrity check: {detail}",
            error_code="BACKUP_DB_CORRUPT",
        )


def inspect_backup(zip_path: str | os.PathLike) -> dict:
    """Fully validate an uploaded backup zip WITHOUT touching the live DB.

    Returns the parsed manifest on success. Raises ValidationError (surfaced as a
    400 with a clear message) for anything that would make a restore unsafe:
    not a zip, missing/corrupt manifest, unknown format version, schema ahead of
    this code, or an invalid/corrupt SQLite database.

    The uploaded DB is extracted to a temp file so its integrity can be verified
    in isolation.
    """
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise ValidationError(
            "That file isn't a Cinefin backup — it isn't a valid zip archive.",
            error_code="BACKUP_NOT_ZIP",
        )

    with zipfile.ZipFile(zip_path, "r") as zf:
        if zf.testzip() is not None:
            raise ValidationError(
                "The backup archive is corrupt.",
                error_code="BACKUP_ZIP_CORRUPT",
            )
        manifest = _read_manifest(zf)
        _check_format_version(manifest)
        _check_migration_state(manifest)

        db_name = manifest.get("database_filename", DB_ARCNAME)
        if db_name not in zf.namelist():
            raise ValidationError(
                "This backup doesn't contain a database file.",
                error_code="BACKUP_DB_MISSING",
            )

        tmp_dir = tempfile.mkdtemp(prefix="cinefin-restore-")
        tmp_db = Path(tmp_dir) / "restore.sqlite3"
        try:
            with zf.open(db_name) as src, open(tmp_db, "wb") as dst:
                # Chunked copy — the DB can be large.
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            _validate_sqlite_file(tmp_db)
        finally:
            tmp_db.unlink(missing_ok=True)
            Path(tmp_dir).rmdir()

    return manifest


def restore_backup(zip_path: str | os.PathLike) -> dict:
    """Validate an uploaded backup and atomically replace the live database.

    Validation (``inspect_backup``) runs first and raises before anything is
    touched. On success the uploaded DB is written to a temp file *beside* the
    live database (same filesystem, so ``os.replace`` is atomic) and swapped in.
    Database connections are closed first; the running process is NOT re-pointed
    at the new file — a restart is required, which the response makes clear.

    Returns ``{"restored": True, "manifest": ..., "restart_required": True}``.
    """
    zip_path = Path(zip_path)
    manifest = inspect_backup(zip_path)  # raises on any problem, live DB untouched

    live = _db_path()
    live.parent.mkdir(parents=True, exist_ok=True)
    db_name = manifest.get("database_filename", DB_ARCNAME)

    # Stage the new DB beside the live file so os.replace is a same-filesystem
    # atomic rename (never a cross-device copy that could half-write).
    staged = live.with_name(live.name + ".restore-tmp")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf, zf.open(db_name) as src, open(staged, "wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)

        # Close Django's connections so the file isn't held open during the swap.
        connection.close()
        os.replace(staged, live)
    finally:
        Path(staged).unlink(missing_ok=True)

    return {"restored": True, "manifest": manifest, "restart_required": True}
