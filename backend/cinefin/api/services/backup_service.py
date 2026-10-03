"""Backup & restore of the SQLite database (everything but the re-derivable usermedia tree).

A backup is a ``.zip`` of ``db.sqlite3`` (a consistent snapshot of the live database) and ``manifest.json``
(format version, app version, timestamp, latest applied migration). Restore fully validates the upload in a
temp location before atomically replacing the live file, and the process must then be restarted.
"""

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

# Bump when the archive layout changes in a way older code can't read; restore refuses newer formats.
BACKUP_FORMAT_VERSION = 1
DB_ARCNAME = "db.sqlite3"
MANIFEST_ARCNAME = "manifest.json"
# Multipart field name the restore endpoint (and the JS client) uses.
RESTORE_FIELD_NAME = "backup"
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _db_path() -> Path:
    # Resolved at runtime: Docker overrides it via SQLITE_PATH and the tests use their own database.
    return Path(connection.settings_dict["NAME"])


def _applied_migrations() -> list[str]:
    return list(MigrationRecorder.Migration.objects.filter(app="api").order_by("id").values_list("name", flat=True))


def _latest_migration() -> str | None:
    applied = _applied_migrations()
    return applied[-1] if applied else None


def backup_filename(when: datetime | None = None) -> str:
    """``cinefin-backup-<YYYYMMDD-HHMMSS>-<version>.zip`` (filesystem-safe)."""
    stamp = (when or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    version = get_version().replace("/", "-").replace(" ", "-")
    return f"cinefin-backup-{stamp}-{version}.zip"


def _snapshot_db(dest: Path) -> None:
    """Write a consistent snapshot of the live DB to ``dest``.

    ``iterdump()`` reads through the live connection, so unlike ``VACUUM INTO`` or the online backup API it
    doesn't block or fail when a transaction is already open on it (Django's test runner wraps each test in one).
    """
    connection.ensure_connection()
    dest_conn = sqlite3.connect(str(dest))
    try:
        dest_conn.executescript("".join(connection.connection.iterdump()))
        dest_conn.commit()
    finally:
        dest_conn.close()


def create_backup(dest_path: str | os.PathLike) -> Path:
    """Write a complete backup zip to ``dest_path`` (via a sibling temp file, renamed into place)."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": get_version(),
        "created_at": datetime.now(UTC).isoformat(),
        "latest_migration": _latest_migration(),
        "database_filename": DB_ARCNAME,
        "includes_media": False,
    }
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
        tmp_zip.unlink(missing_ok=True)


def get_info() -> dict:
    """Readout for the Settings page; only the database *filename* is exposed, never the host path."""
    path = _db_path()
    exists = path.exists()
    return {
        "database_filename": path.name,
        "database_size_bytes": path.stat().st_size if exists else 0,
        "database_modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat() if exists else None,
        "app_version": get_version(),
        "latest_migration": _latest_migration(),
        "includes_media": False,
        "format_version": BACKUP_FORMAT_VERSION,
    }


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        raw = zf.read(MANIFEST_ARCNAME)
    except KeyError:
        raise ValidationError(
            "This file isn't a Cinefin backup — its manifest is missing.", error_code="BACKUP_MANIFEST_MISSING"
        ) from None
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError(
            "The backup's manifest is corrupt and can't be read.", error_code="BACKUP_MANIFEST_INVALID"
        ) from None
    if not isinstance(manifest, dict) or "format_version" not in manifest:
        raise ValidationError("The backup's manifest is missing required fields.", error_code="BACKUP_MANIFEST_INVALID")

    fmt = manifest.get("format_version")
    if not isinstance(fmt, int):
        raise ValidationError("The backup's format version is missing or invalid.", error_code="BACKUP_FORMAT_INVALID")
    if fmt > BACKUP_FORMAT_VERSION:
        raise ValidationError(
            f"This backup was made by a newer version of Cinefin (backup format v{fmt}, "
            f"this install understands up to v{BACKUP_FORMAT_VERSION}). Update Cinefin, then restore.",
            error_code="BACKUP_FORMAT_TOO_NEW",
        )

    # A schema ahead of this code would break it; one behind is fine (migrate rolls it forward). No recorded
    # migration at all (a very old/empty backup) is allowed too.
    latest = manifest.get("latest_migration")
    if latest and latest not in set(_applied_migrations()):
        raise ValidationError(
            f"This backup's database is newer than this install (its latest migration "
            f"'{latest}' isn't known here). Update Cinefin to at least the version that "
            f"created the backup, then restore.",
            error_code="BACKUP_MIGRATION_AHEAD",
        )
    return manifest


def _validate_sqlite_file(path: Path) -> None:
    """Header check + PRAGMA integrity_check, before the live database is touched."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(16)
    except OSError as e:
        raise ValidationError(f"The backup's database couldn't be read: {e}", error_code="BACKUP_DB_UNREADABLE") from e
    if header != _SQLITE_MAGIC:
        raise ValidationError(
            "The file inside the backup isn't a valid SQLite database.", error_code="BACKUP_DB_NOT_SQLITE"
        )
    try:
        conn = sqlite3.connect(str(path))
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise ValidationError(
            f"The backup's database failed its integrity check: {e}", error_code="BACKUP_DB_CORRUPT"
        ) from e
    if not result or result[0] != "ok":
        detail = result[0] if result else "unknown error"
        raise ValidationError(
            f"The backup's database failed its integrity check: {detail}", error_code="BACKUP_DB_CORRUPT"
        )


def _extract_db(zf: zipfile.ZipFile, db_name: str, dest: Path) -> None:
    with zf.open(db_name) as src, open(dest, "wb") as dst:
        while chunk := src.read(1024 * 1024):  # chunked: the DB can be large
            dst.write(chunk)


def inspect_backup(zip_path: str | os.PathLike) -> dict:
    """Fully validate an uploaded backup zip without touching the live DB; returns its manifest."""
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise ValidationError(
            "That file isn't a Cinefin backup — it isn't a valid zip archive.", error_code="BACKUP_NOT_ZIP"
        )
    with zipfile.ZipFile(zip_path, "r") as zf:
        if zf.testzip() is not None:
            raise ValidationError("The backup archive is corrupt.", error_code="BACKUP_ZIP_CORRUPT")
        manifest = _read_manifest(zf)
        db_name = manifest.get("database_filename", DB_ARCNAME)
        if db_name not in zf.namelist():
            raise ValidationError("This backup doesn't contain a database file.", error_code="BACKUP_DB_MISSING")
        with tempfile.TemporaryDirectory(prefix="cinefin-restore-") as tmp_dir:
            tmp_db = Path(tmp_dir) / "restore.sqlite3"
            _extract_db(zf, db_name, tmp_db)
            _validate_sqlite_file(tmp_db)
    return manifest


def restore_backup(zip_path: str | os.PathLike) -> dict:
    """Validate an uploaded backup and atomically replace the live database (a restart is then required)."""
    manifest = inspect_backup(zip_path)  # raises on any problem, live DB untouched
    live = _db_path()
    live.parent.mkdir(parents=True, exist_ok=True)
    # Staged beside the live file so os.replace is a same-filesystem atomic rename.
    staged = live.with_name(live.name + ".restore-tmp")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            _extract_db(zf, manifest.get("database_filename", DB_ARCNAME), staged)
        connection.close()  # don't hold the file open during the swap
        os.replace(staged, live)
    finally:
        staged.unlink(missing_ok=True)
    return {"restored": True, "manifest": manifest, "restart_required": True}
