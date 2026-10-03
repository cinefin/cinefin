from django.db import migrations

# The old layouts' nearest Between screenings option.
BETWEEN = {"spotlight": "films", "board": "week"}
DOORS = (0, 10, 15, 20, 30, 45, 60)  # the Settings page's choices
DROPPED = ("layout", "rotate_minutes", "header", "takeover", "countdown_minutes", "show_showtimes")


def forwards(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    for row in Settings.objects.all():
        kiosk = (row.data or {}).get("kiosk")
        if not isinstance(kiosk, dict):
            continue
        if "layout" in kiosk:
            kiosk["between"] = BETWEEN.get(kiosk["layout"], "whats_on")
        if "countdown_minutes" in kiosk:
            minutes = kiosk["countdown_minutes"] or 0
            kiosk["doors_minutes"] = min(DOORS, key=lambda d: abs(d - minutes))
        for key in DROPPED:
            kiosk.pop(key, None)
        row.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [("api", "0055_playout_host_player_access")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
