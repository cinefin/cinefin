"""Tickets as pictures: columns rows (validation, the bitmap, the images-off text, printing), the designer's
preview, starter designs and the design's own fields."""

from unittest.mock import MagicMock

import pytest

from cinefin.api.exceptions import ValidationError
from cinefin.api.models import Settings
from cinefin.api.services import ticket_raster, ticket_service

pytestmark = pytest.mark.django_db

ROW = {
    "type": "columns",
    "widths": [1, 2],
    "cells": [
        [{"type": "qr", "mode": "content", "content": "https://x.example/{ticket_no}", "width": 100}],
        [
            {"type": "text", "content": "{film_list}", "align": "left", "bold": True},
            {"type": "text", "content": "Seat {seat}", "align": "right"},
        ],
    ],
}


def _ctx():
    return ticket_service.make_ticket_context(
        seat="D7", ticket_no=142, features=[{"title": "Clockers", "year": 1995, "certification": "18"}]
    )


class TestValidation:
    def test_a_row_keeps_its_cells_and_items_with_defaults_filled_in(self):
        (row,) = ticket_service.dump_elements(ticket_service.parse_elements([ROW]))
        assert row["widths"] == [1, 2]
        assert row["cells"][1][1]["align"] == "right" and row["cells"][1][1]["size"] == "normal"

    @pytest.mark.parametrize(
        "row",
        [
            {"type": "columns", "widths": [5, 1]},
            {"type": "columns", "widths": [1, 1], "cells": [[{"type": "barcode", "content": "1"}], []]},
            {"type": "columns", "widths": [1, 1], "cells": [[{"type": "columns", "widths": [1, 1]}], []]},
        ],
    )
    def test_refused(self, row):
        with pytest.raises(ValidationError):
            ticket_service.parse_elements([row])


class TestBitmap:
    @pytest.mark.parametrize(("paper", "cells"), [(384, [124, 248]), (576, [188, 376])])
    def test_cells_split_the_paper_with_a_gutter(self, paper, cells):
        (op,) = ticket_service.render_ticket_ops([ROW], _ctx(), width=paper)
        assert op["op"] == "columns" and op["image"].mode == "1" and op["image"].width == paper
        assert [cell["w"] for cell in op["regions"]] == cells
        assert op["regions"][1]["x"] == cells[0] + ticket_raster.GUTTER

    def test_items_stack_down_their_cell(self):
        (op,) = ticket_service.render_ticket_ops([ROW], _ctx(), width=576)
        qr, (title, seat) = op["regions"][0]["items"][0], op["regions"][1]["items"]
        assert title == {"y": ticket_raster.PADDING, "h": ticket_raster.LINE}
        assert seat["y"] == title["y"] + title["h"]
        assert op["image"].height == max(qr["h"], 2 * ticket_raster.LINE) + 2 * ticket_raster.PADDING


class TestImagesOff:
    def test_text_cells_print_side_by_side_in_the_printer_font(self):
        (op,) = ticket_service.render_ticket_ops([ROW], _ctx(), width=384, images=False)
        # 32 characters: 10 for the first cell, a space, 21 for the second; the QR is dropped.
        assert op["op"] == "text" and op["align"] == "left"
        assert op["value"] == ("           Clockers (1995) [18]\n" + " " * 11 + "              Seat D7\n")


def test_a_row_prints_as_one_image_or_as_text_with_images_off(monkeypatch, tmp_path):
    device = tmp_path / "printer-device"
    device.write_bytes(b"")
    Settings.set("tickets.printer_device", str(device))
    printer = MagicMock()
    monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)

    ticket_service.print_ticket([ROW], _ctx())
    (call,) = printer.image.call_args_list
    assert call.args[0].width == 384 and call.kwargs == {"impl": "bitImageRaster"}

    printer.reset_mock()
    Settings.set("tickets.image_mode", "off")
    ticket_service.print_ticket([ROW], _ctx())
    assert not printer.image.called
    assert any("Seat D7" in c.args[0] for c in printer.text.call_args_list)


class TestDesignFields:
    def test_surprise_qr_picks_from_the_design_and_an_empty_list_prints_none(self):
        qr = [{"type": "qr", "mode": "fun"}]
        (op,) = ticket_service.render_ticket_ops({"elements": qr, "qr_links": ["https://a.example"]}, _ctx())
        assert op["data"] == "https://a.example"
        assert ticket_service.render_ticket_ops({"elements": qr, "qr_links": []}, _ctx()) == []

    def test_validate_design_refuses_unknown_choices(self):
        with pytest.raises(ValidationError):
            ticket_service.validate_design({"date_format": "%s"})
        with pytest.raises(ValidationError):
            ticket_service.validate_design({"qr_links": ["https://a.example"] * 51})
        assert ticket_service.validate_design({"font": "oswald", "elements": None}) == {"font": "oswald"}


def test_migration_moves_the_global_formats_and_links_onto_every_design():
    import importlib

    from django.apps import apps

    from cinefin.api.models import TicketDesign

    migration = importlib.import_module("cinefin.api.migrations.0051_ticket_design_formats")
    instance = Settings._get_instance()
    instance.data["tickets"].update(
        date_format="%Y-%m-%d", time_format="%I:%M %p", qr_fun_links=["https://a.example"], admit_text="ADMIT ONE"
    )
    instance.save()
    design = TicketDesign.objects.create(name="Old", elements=[{"type": "image", "source": "file", "file": "x.png"}])

    migration.move_to_designs(apps, None)

    design.refresh_from_db()
    assert (design.date_format, design.time_format, design.qr_links) == ("%Y-%m-%d", "%I:%M %p", ["https://a.example"])
    assert design.elements == [{"type": "image", "file": "x.png"}]
    stored = Settings.objects.get(id=1).data["tickets"]
    assert not {"date_format", "time_format", "qr_fun_links", "admit_text"} & stored.keys()


class TestPreview:
    def test_a_line_that_prints_nothing_is_a_placeholder_in_the_preview_only(self, monkeypatch, tmp_path):
        design = [{"type": "text", "content": "Hello"}, {"type": "text", "content": "{showtime}"}]
        assert len(ticket_service.render_ticket_ops(design, _ctx())) == 1
        (hello, showtime) = ticket_service.preview_ticket(design, _ctx())["lines"]
        assert not hello["empty"] and showtime["empty"] and showtime["h"] == ticket_raster.PRINTER_LINE
        (op,) = [op for op in ticket_service.render_ticket_ops(design, _ctx(), preview=True) if op["op"] == "empty"]
        assert op["label"] == "{showtime}: blank here"

    def test_a_columns_line_carries_its_cells_on_the_whole_image(self):
        row = {**ROW, "cells": [[], ROW["cells"][1] + [{"type": "image", "file": "missing.png"}]]}
        (line,) = ticket_service.preview_ticket([{"type": "text", "content": "Top"}, row], _ctx())["lines"][1:]
        cells = line["cells"]
        assert [c["x"] for c in cells] == [0, 124 + ticket_raster.GUTTER]
        # Items are placed down the whole image; the missing image is a placeholder, so it takes room.
        title, seat, image = cells[1]["items"]
        assert title["y"] == line["y"] + ticket_raster.PADDING and image["h"] == ticket_raster.LINE


class TestStarters:
    @pytest.mark.parametrize("starter", list(ticket_service.STARTER_DESIGNS))
    def test_every_starter_is_valid_and_previews(self, starter):
        elements = ticket_service.parse_elements(ticket_service.STARTER_DESIGNS[starter])
        assert ticket_service.preview_ticket({"elements": elements}, _ctx())["width"] == 384


def test_migration_sizes_ratings_and_qr_codes_like_images():
    import importlib

    from django.apps import apps

    from cinefin.api.models import TicketDesign

    migration = importlib.import_module("cinefin.api.migrations.0052_ticket_element_widths")
    Settings.set("tickets.paper_width", 576)
    old = [
        {"type": "rating", "scale": "large"},
        {"type": "qr", "mode": "fun", "size": 6},
        {"type": "columns", "widths": [1, 1], "cells": [[{"type": "rating", "scale": "small"}], []]},
    ]
    design = TicketDesign.objects.create(name="Old", elements=old)

    migration.convert(apps, None)

    design.refresh_from_db()
    assert design.elements[0] == {"type": "rating", "width": 35}
    assert design.elements[1] == {"type": "qr", "mode": "fun", "width": 35}  # 6 x 35 modules of 576 dots
    assert design.elements[2]["cells"][0] == [{"type": "rating", "width": 20}]
    ticket_service.parse_elements(design.elements)  # and the result is valid
