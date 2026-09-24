"""Tickets are programme-scoped now: the render context always carries the
programme's features, so film_list prints on every ticket and the old default
design's `{film}` wide-text element would duplicate the film line whenever a
programme has exactly one feature. Strip that exact element from stored
designs that also have a film_list; anything hand-customised beyond the old
default line is left alone."""

from django.db import migrations

OLD_FILM_ELEMENT = {"type": "text", "content": "{film}", "size": "wide"}


def drop_film_element(apps, schema_editor):
    TicketDesign = apps.get_model("api", "TicketDesign")
    for design in TicketDesign.objects.all():
        elements = design.elements or []
        if OLD_FILM_ELEMENT in elements and any(el.get("type") == "film_list" for el in elements):
            design.elements = [el for el in elements if el != OLD_FILM_ELEMENT]
            design.save(update_fields=["elements"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0022_ticketdesign_programme_ticket_design"),
    ]

    operations = [
        migrations.RunPython(drop_film_element, migrations.RunPython.noop),
    ]
