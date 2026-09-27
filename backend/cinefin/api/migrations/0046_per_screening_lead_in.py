"""Lead-ins become per screening: each ProgrammeSchedule owns its lead-in length and steps.

The global `scheduler` settings (lead_in, preshow_commands) are retired. A screening that
used the global length keeps it (start_time is when the lead-in begins, so dropping it would
move the play time); its steps start empty — just the cue — as agreed.
"""

from django.db import migrations, models


def adopt_global_lead_in(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    ProgrammeSchedule = apps.get_model("api", "ProgrammeSchedule")
    row = Settings.objects.filter(id=1).first()
    scheduler = (row.data or {}).get("scheduler", {}) if row else {}
    value = scheduler.get("lead_in")
    seconds = int(value) if isinstance(value, int | float) and value > 0 else 0
    ProgrammeSchedule.objects.filter(lead_in__isnull=True).update(lead_in=seconds)
    if row and "scheduler" in (row.data or {}):
        row.data.pop("scheduler")
        row.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0045_remove_command_show_on_remote"),
    ]

    operations = [
        migrations.AddField(
            model_name="programmeschedule",
            name="preshow",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Lead-in steps: [{"command": id} | {"cue": true}]; none = just the cue',
            ),
        ),
        migrations.RunPython(adopt_global_lead_in, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="programmeschedule",
            name="lead_in",
            field=models.PositiveIntegerField(
                default=0, help_text="Seconds between the lead-in starting and the programme playing"
            ),
        ),
    ]
