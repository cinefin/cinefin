"""Posters are no longer synced to disk.

``Movie.thumbnail`` held a path under ``MEDIA_ROOT/thumbnails`` written by the
sync plugins. It is replaced by ``Movie.poster_key`` — the media server's own
art reference (a Plex ``thumb`` key, a Jellyfin image tag) — and the bytes are
fetched live through ``/api/v2/movies/{id}/poster``.

The old values are paths, not art keys, so they are dropped rather than
migrated: the next sync refills ``poster_key`` from the library listing (see
``sync.plugins.common.sync_poster_key``, which updates it even for films the
incremental pass skips), and until then films render the default poster.

``library.thumbnail_width`` went with the resize-on-sync pipeline — the only
key in the ``library`` category, so the whole category goes.

The stale ``MEDIA_ROOT/thumbnails`` directory is deliberately left alone: this
migration does not delete user files. It is safe to remove by hand.
"""

from django.db import migrations, models


def drop_library_settings(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    for row in Settings.objects.all():
        if isinstance(row.data, dict) and "library" in row.data:
            row.data.pop("library")
            row.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0025_kiosk_layout_cull"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="movie",
            name="thumbnail",
        ),
        migrations.AddField(
            model_name="movie",
            name="poster_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Media-server poster reference (art key / image tag)",
                max_length=500,
            ),
        ),
        migrations.RunPython(drop_library_settings, migrations.RunPython.noop),
    ]
