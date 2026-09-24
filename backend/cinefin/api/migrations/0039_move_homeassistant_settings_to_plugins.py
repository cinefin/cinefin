"""Home Assistant became a contrib plugin: its connection moves from `integrations.homeassistant`
to the plugin settings store (`plugins.homeassistant`), and the `integrations` category goes."""

from django.db import migrations


def forwards(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    for row in Settings.objects.all():
        data = row.data or {}
        integrations = data.pop("integrations", None)
        if integrations is None:
            continue
        ha = (integrations or {}).get("homeassistant") or {}
        values = {k: ha[k] for k in ("url", "token") if ha.get(k)}
        plugins = data.setdefault("plugins", {})
        if values and not plugins.get("homeassistant"):
            plugins["homeassistant"] = values
        row.data = data
        row.save(update_fields=["data"])


def backwards(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    for row in Settings.objects.all():
        data = row.data or {}
        ha = (data.get("plugins") or {}).pop("homeassistant", None) or {}
        data["integrations"] = {"homeassistant": {"url": ha.get("url", ""), "token": ha.get("token", "")}}
        row.data = data
        row.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [("api", "0038_command_provider_plugin_ids")]

    operations = [migrations.RunPython(forwards, backwards)]
