from django.db import migrations, models

import cinefin.api.models.tickets

# The global ticket settings that become per-design, and the pre-designs layout keys nothing reads.
MOVED = ("date_format", "time_format", "qr_fun_links")
DEAD = ("layout", "title_size", "rating_size", "qr_size", "admit_text", "header_text", "footer_text")
DEFAULT_LINKS = [
    "https://www.youtube.com/watch?v=V14PfDDwxlE",
    "https://www.youtube.com/watch?v=8wI4jMxveyI",
    "https://www.youtube.com/watch?v=qPGYBLaF15M",
    "https://www.youtube.com/watch?v=21h0G_gU9Tw",
    "https://www.youtube.com/watch?v=k8V9vgqeUPM",
    "https://www.youtube.com/watch?v=7bXjWRXDFV8",
    "https://www.youtube.com/watch?v=ZqZdfxc-fq0",
]


def move_to_designs(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    TicketDesign = apps.get_model("api", "TicketDesign")
    settings = Settings.objects.filter(id=1).first()
    tickets = (settings.data or {}).get("tickets", {}) if settings else {}
    links = tickets.get("qr_fun_links")
    fields = {
        "date_format": tickets.get("date_format") or "%d/%m/%Y",
        "time_format": tickets.get("time_format") or "%H:%M",
        "qr_links": [str(x).strip() for x in links if str(x).strip()] if isinstance(links, list) else DEFAULT_LINKS,
    }
    for design in TicketDesign.objects.all():
        for key, value in fields.items():
            setattr(design, key, value)
        # Image elements are file-only now; drop the legacy logo/file `source` switch.
        design.elements = [{k: v for k, v in el.items() if k != "source"} for el in design.elements or []]
        design.save()
    if settings:
        for key in MOVED + DEAD:
            tickets.pop(key, None)
        settings.save()


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0050_playout_session_states"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketdesign",
            name="date_format",
            field=models.CharField(default="%d/%m/%Y", max_length=20),
        ),
        migrations.AddField(
            model_name="ticketdesign",
            name="time_format",
            field=models.CharField(default="%H:%M", max_length=20),
        ),
        migrations.AddField(
            model_name="ticketdesign",
            name="qr_links",
            field=models.JSONField(blank=True, default=cinefin.api.models.tickets._default_qr_links),
        ),
        migrations.AddField(
            model_name="ticketdesign",
            name="font",
            field=models.CharField(default="courier", max_length=20),
        ),
        migrations.RunPython(move_to_designs, migrations.RunPython.noop),
    ]
