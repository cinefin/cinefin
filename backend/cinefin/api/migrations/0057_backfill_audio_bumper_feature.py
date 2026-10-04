from django.db import migrations


def forwards(apps, schema_editor):
    """Bind each unbound audio bumper to the feature the old playlist fallback picked: the next one."""
    ProgrammeBlock = apps.get_model("api", "ProgrammeBlock")
    for block in ProgrammeBlock.objects.filter(content_type="audio_bumper", movie__isnull=True, bumper__isnull=True):
        feature = (
            ProgrammeBlock.objects.filter(programme_id=block.programme_id, content_type="movie", order__gt=block.order)
            .order_by("order")
            .first()
        )
        if feature and feature.movie_id:
            block.movie_id = feature.movie_id
            block.save(update_fields=["movie"])


class Migration(migrations.Migration):
    dependencies = [("api", "0056_kiosk_settings")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
