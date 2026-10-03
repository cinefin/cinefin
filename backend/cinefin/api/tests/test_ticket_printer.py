"""Ticket printing: printer selection, layout ops, preview, QR modes, rating images."""

import itertools
from unittest.mock import MagicMock, call

import pytest
from escpos.printer import Dummy

from cinefin.api.exceptions import ValidationError
from cinefin.api.models import Settings, TicketDesign
from cinefin.api.services import ticket_service

pytestmark = pytest.mark.django_db


class TestOpenPrinter:
    def test_default_is_file_printer_with_configured_device(self, monkeypatch):
        opened = {}
        monkeypatch.setattr(
            ticket_service, "FilePrinter", lambda device, **kw: opened.update(device=device, **kw) or "printer"
        )
        Settings.set("tickets.printer_device", "/dev/usb/lp1")

        assert ticket_service.open_printer() == "printer"
        assert opened == {"device": "/dev/usb/lp1", "profile": ticket_service.PRINTER_PROFILES[384]}

    def test_network_printer_uses_host_and_port(self, monkeypatch):
        opened = {}
        monkeypatch.setattr(
            ticket_service, "NetworkPrinter", lambda host, **kw: opened.update(host=host, **kw) or "netprinter"
        )
        Settings.set("tickets.printer_type", "network")
        Settings.set("tickets.printer_host", "10.0.0.20")
        Settings.set("tickets.printer_port", 9101)

        assert ticket_service.open_printer() == "netprinter"
        assert opened["host"] == "10.0.0.20"
        assert opened["port"] == 9101
        assert opened["profile"] == ticket_service.PRINTER_PROFILES[384]
        assert opened["timeout"] == 30

    def test_network_without_host_raises(self):
        Settings.set("tickets.printer_type", "network")
        Settings.set("tickets.printer_host", "  ")

        with pytest.raises(RuntimeError, match="no host configured"):
            ticket_service.open_printer()


class TestRenderDesign:
    def _ctx(self, **kw):
        base = dict(features=[{"title": "Clockers", "year": 1995, "certification": "18"}], seat="D7", ticket_no=42)
        base.update(kw)
        return ticket_service.make_ticket_context(**base)

    def test_text_tokens_and_empty_skip(self):
        ops = ticket_service.render_ticket_ops(
            [
                {"type": "text", "content": "{film}"},
                {"type": "text", "content": "{seat}"},
                {"type": "text", "content": "Ticket #{ticket_no}"},
                {"type": "text", "content": "{programme}"},  # resolves empty -> skipped
            ],
            self._ctx(programme_name=""),
        )
        values = [o["value"] for o in ops]
        assert "Clockers (1995)\n" in values
        assert "D7\n" in values
        assert "Ticket #42\n" in values
        assert all(v.strip() for v in values)

    def test_film_list_token_expands_per_feature(self):
        ctx = ticket_service.make_ticket_context(
            features=[
                {"title": "Dune", "year": 2021, "certification": "12A"},
                {"title": "Aliens", "year": 1986, "certification": "18"},
            ]
        )
        ops = ticket_service.render_ticket_ops([{"type": "text", "content": "{film_list}", "bold": True}], ctx)
        assert len(ops) == 1
        assert ops[0]["value"] == "Dune (2021) [12A]\nAliens (1986) [18]\n"
        assert ops[0]["bold"] is True

    def test_effective_certification_is_most_restrictive(self):
        assert (
            ticket_service.effective_certification(
                [{"certification": "PG"}, {"certification": "15"}, {"certification": "12A"}]
            )
            == "15"
        )
        assert (
            ticket_service.effective_certification(
                [{"certification": "NC-17"}, {"certification": "PG"}, {"certification": None}]
            )
            == "PG"
        )
        assert ticket_service.effective_certification([{"certification": "XX"}, {"title": "no cert"}]) is None
        assert ticket_service.effective_certification([]) is None


@pytest.fixture
def fake_device(tmp_path):
    device = tmp_path / "printer-device"
    device.write_bytes(b"")
    Settings.set("tickets.printer_device", str(device))
    return device


class TestPrintAndPreview:
    def test_preview_renders_the_default_design(self):
        ctx = ticket_service.make_ticket_context(
            features=[{"title": "Clockers", "year": 1995, "certification": "18"}], seat="D7", ticket_no=42
        )
        ops = ticket_service.render_ticket_ops(None, ctx, width=384)
        texts = [op["value"].strip() for op in ops if op["op"] == "text"]
        assert "ADMIT ONE" in texts
        assert "D7" in texts
        assert "Clockers (1995) [18]" in texts
        assert "=" * 32 in texts  # the divider spans the 58 mm paper's 32 characters
        assert [op["op"] for op in ops].count("rating") == 1 and [op["op"] for op in ops].count("qr") == 1

        preview = ticket_service.preview_ticket(None, ctx, width=384)
        assert preview["url"].startswith("data:image/png;base64,") and preview["width"] == 384
        # One line per element, stacked down the image without overlapping.
        assert [line["element"] for line in preview["lines"]] == list(range(10))
        assert all(a["y"] + a["h"] == b["y"] for a, b in itertools.pairwise(preview["lines"]))

    def test_print_walks_ops_and_surfaces_failures(self, monkeypatch, fake_device):
        printer = MagicMock()
        monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
        ticket_service.print_ticket(None, ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1"))
        assert printer.text.called and printer.close.called

        monkeypatch.setattr(ticket_service, "open_printer", lambda: (_ for _ in ()).throw(OSError("No such device")))
        with pytest.raises(RuntimeError, match="No such device"):
            ticket_service.print_ticket(None, ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1"))

    def test_image_mode_off_prints_no_images(self, monkeypatch, fake_device, tmp_path, settings):
        from PIL import Image

        settings.MEDIA_ROOT = str(tmp_path)
        images = tmp_path / "ticket_images"
        images.mkdir(parents=True)
        Image.new("RGB", (40, 20), "black").save(images / "logo.png")
        design = TicketDesign(name="Imaged", elements=[{"type": "image", "file": "logo.png"}])

        Settings.set("tickets.image_mode", "off")
        printer = MagicMock()
        monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
        ticket_service.print_ticket(design, ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1"))
        assert not printer.image.called
        assert printer.text.called

    @pytest.mark.parametrize(
        ("mode", "expected"), [("off", None), ("partial", b"\x1dV\x01"), ("full", b"\x1dV\x00"), ("bogus", None)]
    )
    def test_cut_follows_the_setting(self, monkeypatch, fake_device, mode, expected):
        Settings.set("tickets.cut", mode)
        printer = MagicMock()
        monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
        ticket_service.print_ticket(None, ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1"))
        raws = [c.args[0] for c in printer._raw.call_args_list]
        if expected is None:
            assert not raws
        else:
            # The cut is the last thing sent, after the feed lines.
            assert raws == [expected]
            assert printer.method_calls[-2] == call._raw(expected)
        assert not printer.cut.called

    def test_print_run_cuts_after_every_ticket(self, monkeypatch, fake_device):
        Settings.set("tickets.cut", "partial")
        printer = MagicMock()
        monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
        ticket_service.print_run(kind="programme", title="X", design=None, seats=["A1", "A2", "A3"])
        assert printer._raw.call_args_list == [call(b"\x1dV\x01")] * 3

    def test_feed_lines_clamps_bad_values(self):
        Settings.set("tickets.feed_lines", "oops")
        assert ticket_service.feed_lines() == 2
        Settings.set("tickets.feed_lines", 99)
        assert ticket_service.feed_lines() == 20
        Settings.set("tickets.feed_lines", -5)
        assert ticket_service.feed_lines() == 0


def _ctx():
    return ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1", ticket_no=142)


class TestBarcodes:
    @pytest.mark.parametrize(
        ("symbology", "data", "expected"),
        [
            ("code128", "T142", "T142"),
            ("code39", "a-1", "A-1"),
            ("ean13", "142", "000000000142"),
            ("ean8", "142", "0000142"),
            ("upca", "142", "00000000142"),
            ("itf", "142", "0142"),
            ("itf", "1420", "1420"),
            ("codabar", "142", "A142A"),
        ],
    )
    def test_data_is_shaped_for_the_symbology(self, symbology, data, expected):
        assert ticket_service.barcode_data(symbology, data) == expected

    @pytest.mark.parametrize(
        ("symbology", "data"),
        [("ean13", "T142"), ("ean8", "123456789"), ("code39", "a_b"), ("codabar", "AB"), ("code128", "café")],
    )
    def test_data_it_cannot_carry_is_refused(self, symbology, data):
        with pytest.raises(ValueError):
            ticket_service.barcode_data(symbology, data)

    def test_printer_drawn_code128_carries_the_code_set_prefix(self):
        # Epson (TM-m30 etc.) prints nothing for GS k 73 data without a {A/{B/{C code-set prefix.
        dummy = Dummy(profile=ticket_service.PRINTER_PROFILES[576])
        ticket_service._print_barcode(dummy, {"symbology": "code128", "data": "T{142"})
        assert dummy.output.endswith(b"\x1dkI\x08{BT{{142")

    def test_printer_drawn_ean13_sends_the_padded_digits(self):
        dummy = Dummy(profile=ticket_service.PRINTER_PROFILES[576])
        ticket_service._print_barcode(dummy, {"symbology": "ean13", "data": "000000000142"})
        assert dummy.output.endswith(b"\x1dk\x02000000000142\x00")

    def test_left_aligned_barcode_is_not_recentred(self):
        dummy = Dummy(profile=ticket_service.PRINTER_PROFILES[576])
        ticket_service._print_barcode(dummy, {"symbology": "code128", "data": "142", "align": "left"})
        assert b"\x1ba\x01" not in dummy.output

    def test_profile_without_a_barcode_engine_draws_an_image(self):
        dummy = Dummy(profile=ticket_service.PRINTER_PROFILES[384])
        ticket_service._print_barcode(dummy, {"symbology": "ean13", "data": "000000000142"})
        assert b"\x1dk" not in dummy.output and len(dummy.output) > 500

    def test_unprintable_barcode_is_flagged_in_preview_and_skipped_in_print(self, monkeypatch, fake_device):
        elements = [{"type": "barcode", "symbology": "ean13", "content": "T{ticket_no}"}]
        (op,) = ticket_service.render_ticket_ops(elements, _ctx(), preview=True)
        assert op["problem"] == "EAN-13 takes digits only"

        printer = MagicMock()
        monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
        ticket_service.print_ticket(elements, _ctx())
        assert not printer.barcode.called

    def test_validate_refuses_an_unknown_symbology(self):
        (el,) = ticket_service.parse_elements([{"type": "barcode", "content": "1", "symbology": "ean8"}])
        assert el.symbology == "ean8"
        with pytest.raises(ValidationError, match="symbology"):
            ticket_service.parse_elements([{"type": "barcode", "content": "1", "symbology": "pdf417"}])


class TestQrOptions:
    def test_validate_keeps_known_error_levels_and_renders(self):
        (el,) = ticket_service.parse_elements([{"type": "qr", "error": "high", "render": "printer"}])
        assert (el.error, el.render, el.width) == ("high", "printer", 50)
        with pytest.raises(ValidationError):
            ticket_service.parse_elements([{"type": "qr", "error": "extreme"}])

    @pytest.mark.parametrize(("paper", "width", "box"), [(384, 50, 8), (384, 100, 16), (576, 25, 6)])
    def test_the_width_picks_the_module_size(self, paper, width, box):
        # "x" is a 21-module code; with its border, 23 modules across.
        el = {"type": "qr", "mode": "content", "content": "x", "width": width}
        (op,) = ticket_service.render_ticket_ops([el], _ctx(), width=paper)
        assert op["size"] == min(16, paper * width // 100 // 23) == box

    @pytest.mark.parametrize(("render", "native"), [("image", False), ("printer", True)])
    def test_qr_prints_with_its_error_level_and_render(self, monkeypatch, fake_device, render, native):
        from escpos.constants import QR_ECLEVEL_Q

        printer = MagicMock()
        monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
        elements = [
            {"type": "qr", "mode": "content", "content": "x", "width": 30, "error": "quartile", "render": render}
        ]
        ticket_service.print_ticket(elements, _ctx())
        # 30% of 384 dots is 115; "x" at quartile is 21 modules, 23 with the border: 5-dot modules.
        printer.qr.assert_called_once_with("x", ec=QR_ECLEVEL_Q, size=5, **({"native": True} if native else {}))

    def test_printer_drawn_qr_sends_the_qr_commands(self):
        dummy = Dummy(profile=ticket_service.PRINTER_PROFILES[576])
        ticket_service._print_qr(dummy, {"data": "https://x.y", "size": 6, "error": "high", "render": "printer"})
        assert b"\x1d(k" in dummy.output and len(dummy.output) < 100


class TestImageSize:
    @pytest.fixture
    def logo(self, settings, tmp_path):
        from PIL import Image

        settings.MEDIA_ROOT = str(tmp_path)
        (tmp_path / "ticket_images").mkdir()
        Image.new("RGB", (100, 40), "black").save(tmp_path / "ticket_images" / "logo.png")
        return "logo.png"

    @pytest.mark.parametrize(("width", "height"), [(None, 40), (50, 77), (100, 154), (10, 15)])
    def test_preview_scales_to_the_share_of_the_paper(self, logo, width, height):
        el = {"type": "image", "file": logo, **({"width": width} if width else {})}
        (line,) = ticket_service.preview_ticket([el], _ctx(), width=384)["lines"]
        assert line["h"] == height

    def test_print_sends_the_scaled_image(self, monkeypatch, fake_device, logo):
        printer = MagicMock()
        monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
        ticket_service.print_ticket([{"type": "image", "file": logo, "width": 75}], _ctx())
        assert printer.image.call_args.args[0].size == (288, 115)

    def test_an_image_in_a_cell_scales_to_its_cell(self, logo):
        row = {"type": "columns", "widths": [1, 1], "cells": [[{"type": "image", "file": logo, "width": 50}], []]}
        (op,) = ticket_service.render_ticket_ops([row], _ctx(), width=384)
        # Cells are 186 dots wide (384 less a 12-dot gutter, halved): half of that is 93.
        assert op["regions"][0]["items"][0]["h"] == round(40 * 93 / 100)

    @pytest.mark.parametrize("width", [500, 3, "big"])
    def test_validate_refuses_a_width_out_of_range(self, width):
        with pytest.raises(ValidationError, match="width"):
            ticket_service.parse_elements([{"type": "image", "file": "a.png", "width": width}])

    def test_the_file_name_cannot_climb_out_of_the_library(self):
        (el,) = ticket_service.parse_elements([{"type": "image", "file": "../../etc/passwd"}])
        assert el.file == "passwd"
