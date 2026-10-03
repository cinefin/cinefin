from django.db import migrations

# Ratings and QR codes are now sized like images: a share (%) of the paper, or of their cell.
RATING_SCALES = {"small": 20, "medium": 25, "large": 35}
# A typical ticket QR (a surprise link) is about 35 modules across, its border included.
QR_MODULES = 35


def _share(dots: float, width: int) -> int:
    return max(10, min(100, 5 * round(dots * 100 / width / 5)))


def _convert(elements: list, paper: int) -> list:
    out = []
    for el in elements or []:
        el = dict(el)
        if el.get("type") == "rating":
            el["width"] = RATING_SCALES.get(el.pop("scale", "medium"), 25)
        elif el.get("type") == "qr":
            el["width"] = _share(int(el.pop("size", 6) or 6) * QR_MODULES, paper)
        elif el.get("type") == "columns":
            el["cells"] = [_convert(cell, paper) for cell in el.get("cells") or []]
        out.append(el)
    return out


def convert(apps, schema_editor):
    Settings = apps.get_model("api", "Settings")
    TicketDesign = apps.get_model("api", "TicketDesign")
    settings = Settings.objects.filter(id=1).first()
    paper = ((settings.data or {}).get("tickets", {}) if settings else {}).get("paper_width") or 384
    for design in TicketDesign.objects.all():
        design.elements = _convert(design.elements, paper if paper in (384, 576) else 384)
        design.save(update_fields=["elements"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0051_ticket_design_formats"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop),
    ]
