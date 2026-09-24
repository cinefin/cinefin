"""Convert absolute Bumper.file_path values to MEDIA_ROOT-relative.

User-media paths are now stored relative to MEDIA_ROOT so the library survives a
moved/restored usermedia volume (see api/utils/media_paths.py). Existing rows
hold absolute paths — rewrite them to their usermedia-relative tail. The
relativisation is inlined (not imported) so this migration is frozen in time.
"""

import os

from django.conf import settings
from django.db import migrations

_MARKER = os.sep + "usermedia" + os.sep
_SUBDIRS = ("media", "trailers", "screenshots", "ratings", "titles", "certifications", "uploads")


def _relative(path: str) -> str | None:
    if not path or not os.path.isabs(path):
        return None
    root = str(settings.MEDIA_ROOT)
    if path == root or path.startswith(root + os.sep):
        return os.path.relpath(path, root)
    idx = path.rfind(_MARKER)
    if idx != -1:
        return path[idx + len(_MARKER) :]
    parts = path.split(os.sep)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in _SUBDIRS:
            return os.sep.join(parts[i:])
    return None


def relativise(apps, schema_editor):
    Bumper = apps.get_model("api", "Bumper")
    for bumper in Bumper.objects.exclude(file_path="").iterator():
        rel = _relative(bumper.file_path)
        if rel and rel != bumper.file_path:
            bumper.file_path = rel
            bumper.save(update_fields=["file_path"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0035_alter_tag_options_tag_color"),
    ]

    # Irreversible in practice (the original absolute root is lost), but a no-op
    # reverse keeps the migration graph reversible for tests/tooling.
    operations = [migrations.RunPython(relativise, migrations.RunPython.noop)]
