"""Three kiosk layouts were removed (now & next, marquee, lightbox — they
used the screen poorly or broke with portrait artwork). Remap a saved
kiosk.layout to the nearest survivor and drop the retired dwell-time
settings (the kiosk uses fixed pacing defaults now; URL params still
override per screen)."""

from django.db import migrations

LAYOUT_MAP = {"nownext": "split", "marquee": "board", "lightbox": "spotlight"}


def cull_kiosk_settings(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    for row in Settings.objects.all():
        kiosk = (row.data or {}).get("kiosk")
        if not isinstance(kiosk, dict):
            continue
        changed = False
        if kiosk.get("layout") in LAYOUT_MAP:
            kiosk["layout"] = LAYOUT_MAP[kiosk["layout"]]
            changed = True
        for key in ("spotlight_seconds", "wall_page_seconds"):
            if key in kiosk:
                kiosk.pop(key)
                changed = True
        if changed:
            row.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0024_film_list_element_to_token"),
    ]

    operations = [
        migrations.RunPython(cull_kiosk_settings, migrations.RunPython.noop),
    ]
