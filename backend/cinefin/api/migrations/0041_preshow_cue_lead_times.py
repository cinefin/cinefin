"""Give pre-show commands a lead time.

``scheduler.preshow_commands`` was a plain JSON list of command ids, all fired at
the show start. Cues now carry a per-cue lead (seconds before the scheduled start
to fire), so each entry becomes ``{"command": <id>, "lead": <seconds>}``. Existing
bare-int entries convert to lead 0 (fire at start — the old behaviour)."""

from django.db import migrations


def forwards(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    for row in Settings.objects.all():
        data = row.data or {}
        scheduler = data.get("scheduler")
        if not isinstance(scheduler, dict):
            continue
        preshow = scheduler.get("preshow_commands")
        if not isinstance(preshow, list):
            continue
        converted = [
            {"command": i, "lead": 0}
            for i in preshow
            if isinstance(i, int) and not isinstance(i, bool)
        ]
        if converted != preshow:
            scheduler["preshow_commands"] = converted
            row.data = data
            row.save(update_fields=["data"])


def backwards(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    for row in Settings.objects.all():
        data = row.data or {}
        scheduler = data.get("scheduler")
        if not isinstance(scheduler, dict):
            continue
        preshow = scheduler.get("preshow_commands")
        if not isinstance(preshow, list):
            continue
        reverted = [c["command"] for c in preshow if isinstance(c, dict) and isinstance(c.get("command"), int)]
        if reverted != preshow:
            scheduler["preshow_commands"] = reverted
            row.data = data
            row.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0040_remove_job_schedule_delete_syncschedule"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
