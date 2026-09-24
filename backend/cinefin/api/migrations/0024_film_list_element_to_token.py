"""The film_list element type is gone: the film list is now the {film_list}
token, usable in any text element (it expands to one "Title (Year) [cert]"
line per feature). Convert stored film_list elements to equivalent text
elements, keeping their styling; the per-element show_* flags are dropped
(the token's format is fixed)."""

from django.db import migrations


def film_list_to_text(apps, schema_editor):
    TicketDesign = apps.get_model("api", "TicketDesign")
    for design in TicketDesign.objects.all():
        elements = design.elements or []
        if not any(el.get("type") == "film_list" for el in elements):
            continue
        converted = []
        for el in elements:
            if el.get("type") == "film_list":
                el = {
                    "type": "text",
                    "content": "{film_list}",
                    **{k: el[k] for k in ("align", "size", "bold", "invert") if k in el},
                }
            converted.append(el)
        design.elements = converted
        design.save(update_fields=["elements"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0023_drop_film_element_from_designs"),
    ]

    operations = [
        migrations.RunPython(film_list_to_text, migrations.RunPython.noop),
    ]
