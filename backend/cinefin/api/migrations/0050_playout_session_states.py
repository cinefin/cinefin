from django.db import migrations

# The programme lifecycle is now not_loaded, loaded and running: pause is mpv's
# own, and a finished programme goes straight to standby.
OLD_STATES = {"paused": "running", "completed": "not_loaded", "error": "not_loaded"}


def reduce_states(apps, schema_editor):
    PlayoutSession = apps.get_model("api", "PlayoutSession")
    for old, new in OLD_STATES.items():
        fields = {"state": new} if new != "not_loaded" else {"state": new, "programme": None}
        PlayoutSession.objects.filter(state=old).update(**fields)


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0049_standby"),
    ]

    operations = [
        migrations.RunPython(reduce_states, migrations.RunPython.noop),
    ]
