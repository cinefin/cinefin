"""
Backup & restore API (Django Ninja).

Thin HTTP boundary over ``services/backup_service.py``:

* ``GET  /backup/info``     — current DB size / filename / version readout.
* ``GET  /backup/download`` — streams a full backup zip (DB + manifest).
* ``POST /backup/restore``  — validates an uploaded backup, then atomically
  swaps in its database. A restart is required afterward (the DB file is
  replaced on disk; the running process is not hot-swapped).

The restore upload is multipart with field name ``backup``
(``backup_service.RESTORE_FIELD_NAME``) — the JS client uses the same name.
"""

import logging
import tempfile
from pathlib import Path

from django.http import FileResponse, HttpRequest
from ninja import File, Router, Schema, Status, UploadedFile

from cinefin.api.schemas.base import ErrorResponseSchema, SuccessResponseSchema
from cinefin.api.services import backup_service

logger = logging.getLogger(__name__)

backup_api = Router()


# ---- Schemas ----


class BackupInfoDataSchema(Schema):
    database_filename: str
    database_size_bytes: int
    database_modified_at: str | None = None
    app_version: str
    latest_migration: str | None = None
    includes_media: bool
    format_version: int


class BackupInfoResponseSchema(SuccessResponseSchema):
    data: BackupInfoDataSchema


class RestoreManifestSchema(Schema):
    format_version: int
    app_version: str | None = None
    created_at: str | None = None
    latest_migration: str | None = None
    includes_media: bool = False


class RestoreDataSchema(Schema):
    restored: bool
    restart_required: bool
    manifest: RestoreManifestSchema


class RestoreResponseSchema(SuccessResponseSchema):
    data: RestoreDataSchema


# ---- Endpoints ----


@backup_api.get("/info", response={200: BackupInfoResponseSchema, 500: ErrorResponseSchema})
def backup_info(request: HttpRequest):
    """Current database size, filename, last-modified and app version.

    The absolute host path is never exposed — only the database filename.
    Media files are not part of a backup (``includes_media`` is always False).
    """
    return Status(
        200,
        BackupInfoResponseSchema(
            message="Backup info retrieved",
            data=BackupInfoDataSchema(**backup_service.get_info()),
        ),
    )


@backup_api.get("/download", response={500: ErrorResponseSchema})
def backup_download(request: HttpRequest):
    """Stream a full backup zip (consistent DB snapshot + manifest).

    The zip is built to a temp file and streamed with FileResponse; the temp
    file is removed once the response has been fully sent.
    """
    filename = backup_service.backup_filename()
    tmp_path = Path(tempfile.mkstemp(prefix="cinefin-backup-dl-", suffix=".zip")[1])
    try:
        backup_service.create_backup(tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    fh = open(tmp_path, "rb")  # noqa: SIM115 — FileResponse owns and closes the handle
    response = FileResponse(fh, as_attachment=True, filename=filename, content_type="application/zip")

    # Delete the temp file once the response is closed (streaming finished).
    original_close = response.close

    def _close_and_cleanup():
        original_close()
        tmp_path.unlink(missing_ok=True)

    response.close = _close_and_cleanup
    return response


@backup_api.post(
    "/restore",
    response={200: RestoreResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def backup_restore(request: HttpRequest, backup: UploadedFile = File(...)):
    """Restore from an uploaded backup zip (multipart field name: ``backup``).

    The upload is validated in full before the live database is touched — the
    zip must open, its manifest must parse and use a known format version, its
    migration state must not be ahead of this code, and the embedded database
    must pass a SQLite integrity check in a temp location. Only then is the live
    database replaced atomically on disk. **A restart is required afterward** —
    the running process keeps using the old connection until it is restarted
    (``git pull`` / systemctl restart / docker restart).
    """
    tmp_path = Path(tempfile.mkstemp(prefix="cinefin-restore-upload-", suffix=".zip")[1])
    try:
        with open(tmp_path, "wb") as dst:
            for chunk in backup.chunks():
                dst.write(chunk)
        # Raises ValidationError (400) on any unsafe/invalid upload, live DB untouched.
        result = backup_service.restore_backup(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return Status(
        200,
        RestoreResponseSchema(
            message="Backup restored. Restart Cinefin now to load the restored database.",
            data=RestoreDataSchema(
                restored=result["restored"],
                restart_required=result["restart_required"],
                manifest=RestoreManifestSchema(**result["manifest"]),
            ),
        ),
    )
