"""Convert the remaining absolute user-media paths to MEDIA_ROOT-relative.

Follows 0036 (bumpers): trailers, certification cards, and generated title cards
(+ their background files) are now stored relative to MEDIA_ROOT so the library
survives a moved/restored usermedia volume. This is the one-time heal of legacy
absolute rows — rewrite each to its usermedia-relative tail. The runtime code no
longer re-bases; it just joins MEDIA_ROOT, so every row must end up relative.
"""

import os

from django.conf import settings
from django.db import migrations

_MARKER = os.sep + "usermedia" + os.sep
_SUBDIRS = (
    "media",
    "trailers",
    "screenshots",
    "ratings",
    "titles",
    "programme_titles",
    "certifications",
    "uploads",
)


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


def _relativise_field(queryset, field):
    for row in queryset.iterator():
        value = getattr(row, field)
        rel = _relative(value)
        if rel and rel != value:
            setattr(row, field, rel)
            row.save(update_fields=[field])


def relativise(apps, schema_editor):
    Trailer = apps.get_model("api", "Trailer")
    Certification = apps.get_model("api", "Certification")
    Programme = apps.get_model("api", "Programme")

    _relativise_field(Trailer.objects.exclude(file_path=""), "file_path")
    _relativise_field(Certification.objects.exclude(file_path=""), "file_path")
    _relativise_field(Programme.objects.exclude(title_file=""), "title_file")
    _relativise_field(Programme.objects.exclude(title_background_file=""), "title_background_file")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0036_relativise_bumper_paths"),
    ]

    operations = [migrations.RunPython(relativise, migrations.RunPython.noop)]
