"""Ticket printing: printer selection, layout ops, preview, QR modes, rating images."""

import itertools
from unittest.mock import MagicMock, call

import pytest
from escpos.printer import Dummy

from cinefin.api.exceptions import ValidationError
from cinefin.api.models import Settings
from cinefin.api.services import ticket_service

pytestmark = pytest.mark.django_db


def test_open_printer_follows_the_printer_type(monkeypatch):
    opened = {}
    monkeypatch.setattr(ticket_service, "FilePrinter", lambda device, **kw: opened.update(device=device, **kw) or "f")
    monkeypatch.setattr(ticket_service, "NetworkPrinter", lambda host, **kw: opened.update(host=host, **kw) or "n")
    profile = ticket_service.PRINTER_PROFILES[384]
    Settings.set("tickets.printer_device", "/dev/usb/lp1")
    assert ticket_service.open_printer() == "f"
    assert opened == {"device": "/dev/usb/lp1", "profile": profile}

    opened.clear()
    Settings.set("tickets.printer_type", "network")
    Settings.set("tickets.printer_host", "10.0.0.20")
    Settings.set("tickets.printer_port", 9101)
    assert ticket_service.open_printer() == "n"
    assert opened == {"host": "10.0.0.20", "port": 9101, "profile": profile, "timeout": 30}

    Settings.set("tickets.printer_host", "  ")
    with pytest.raises(RuntimeError, match="no host configured"):
        ticket_service.open_printer()


class TestRenderDesign:
    def _ctx(self, **kw):
        base = dict(features=[{"title": "Clockers", "year": 1995, "certification": "18"}], seat="D7", ticket_no=42)
        base.update(kw)
        return ticket_service.make_ticket_context(**base)

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

    @pytest.mark.parametrize(
        ("certs", "expected"), [(["PG", "15", "12A"], "15"), (["NC-17", "PG", None], "PG"), (["XX"], None), ([], None)]
    )
    def test_effective_certification_is_most_restrictive(self, certs, expected):
        assert ticket_service.effective_certification([{"certification": c} for c in certs]) == expected


@pytest.fixture
def printer(tmp_path, monkeypatch):
    device = tmp_path / "printer-device"
    device.write_bytes(b"")
    Settings.set("tickets.printer_device", str(device))
    printer = MagicMock()
    monkeypatch.setattr(ticket_service, "open_printer", lambda: printer)
    return printer


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

    def test_print_walks_ops_and_surfaces_failures(self, monkeypatch, printer):
        ticket_service.print_ticket(None, ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1"))
        assert printer.text.called and printer.close.called

        monkeypatch.setattr(ticket_service, "open_printer", lambda: (_ for _ in ()).throw(OSError("No such device")))
        with pytest.raises(RuntimeError, match="No such device"):
            ticket_service.print_ticket(None, ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1"))

    @pytest.mark.parametrize(
        ("mode", "expected"), [("off", None), ("partial", b"\x1dV\x01"), ("full", b"\x1dV\x00"), ("bogus", None)]
    )
    def test_cut_follows_the_setting(self, printer, mode, expected):
        Settings.set("tickets.cut", mode)
        ticket_service.print_ticket(None, ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1"))
        raws = [c.args[0] for c in printer._raw.call_args_list]
        if expected is None:
            assert not raws
        else:
            # The cut is the last thing sent, after the feed lines.
            assert raws == [expected]
            assert printer.method_calls[-2] == call._raw(expected)
        assert not printer.cut.called

    @pytest.mark.parametrize(("value", "lines"), [("oops", 2), (99, 20), (-5, 0)])
    def test_feed_lines_clamps_bad_values(self, value, lines):
        Settings.set("tickets.feed_lines", value)
        assert ticket_service.feed_lines() == lines


def _ctx():
    return ticket_service.make_ticket_context(features=[{"title": "X"}], seat="A1", ticket_no=142)


class TestBarcodes:
    @pytest.mark.parametrize(
        ("symbology", "data", "expected"),
        [
            ("code128", "T142", "T142"),
            ("code39", "a-1", "A-1"),
            ("ean13", "142", "000000000142"),
            ("itf", "142", "0142"),
            ("codabar", "142", "A142A"),
        ],
    )
    def test_data_is_shaped_for_the_symbology(self, symbology, data, expected):
        assert ticket_service.barcode_data(symbology, data) == expected

    @pytest.mark.parametrize(
        ("symbology", "data"),
        [("ean13", "T142"), ("ean8", "123456789"), ("code128", "café")],
    )
    def test_data_it_cannot_carry_is_refused(self, symbology, data):
        with pytest.raises(ValueError):
            ticket_service.barcode_data(symbology, data)

    @pytest.mark.parametrize(
        ("symbology", "data", "tail"),
        [
            # Epson (TM-m30 etc.) prints nothing for GS k 73 data without a {A/{B/{C code-set prefix.
            ("code128", "T{142", b"\x1dkI\x08{BT{{142"),
            ("ean13", "000000000142", b"\x1dk\x02000000000142\x00"),
        ],
    )
    def test_printer_drawn_barcode_bytes(self, symbology, data, tail):
        dummy = Dummy(profile=ticket_service.PRINTER_PROFILES[576])
        ticket_service._print_barcode(dummy, {"symbology": symbology, "data": data})
        assert dummy.output.endswith(tail)

    def test_unprintable_barcode_is_flagged_in_preview_and_skipped_in_print(self, printer):
        elements = [{"type": "barcode", "symbology": "ean13", "content": "T{ticket_no}"}]
        (op,) = ticket_service.render_ticket_ops(elements, _ctx(), preview=True)
        assert op["problem"] == "EAN-13 takes digits only"

        ticket_service.print_ticket(elements, _ctx())
        assert not printer.barcode.called


class TestQrOptions:
    @pytest.mark.parametrize(
        "element",
        [
            {"type": "qr", "error": "extreme"},
            {"type": "barcode", "content": "1", "symbology": "pdf417"},
            {"type": "image", "file": "a.png", "width": 500},
            {"type": "image", "file": "a.png", "width": "big"},
        ],
    )
    def test_validate_refuses_unknown_choices(self, element):
        with pytest.raises(ValidationError):
            ticket_service.parse_elements([element])

    @pytest.mark.parametrize(("paper", "width", "box"), [(384, 50, 8), (384, 100, 16), (576, 25, 6)])
    def test_the_width_picks_the_module_size(self, paper, width, box):
        # "x" is a 21-module code; with its border, 23 modules across.
        el = {"type": "qr", "mode": "content", "content": "x", "width": width}
        (op,) = ticket_service.render_ticket_ops([el], _ctx(), width=paper)
        assert op["size"] == min(16, paper * width // 100 // 23) == box

    @pytest.mark.parametrize(("render", "native"), [("image", False), ("printer", True)])
    def test_qr_prints_with_its_error_level_and_render(self, printer, render, native):
        from escpos.constants import QR_ECLEVEL_Q

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

    @pytest.mark.parametrize(("width", "height"), [(None, 40), (50, 77)])
    def test_preview_scales_to_the_share_of_the_paper(self, logo, width, height):
        el = {"type": "image", "file": logo, **({"width": width} if width else {})}
        (line,) = ticket_service.preview_ticket([el], _ctx(), width=384)["lines"]
        assert line["h"] == height

    def test_the_file_name_cannot_climb_out_of_the_library(self):
        (el,) = ticket_service.parse_elements([{"type": "image", "file": "../../etc/passwd"}])
        assert el.file == "passwd"
