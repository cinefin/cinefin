"""Ticket printing: printer selection, layout ops, preview, QR modes, rating images."""

from unittest.mock import MagicMock

import pytest

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
        lines = ticket_service.preview_ticket(ticket_service.DEFAULT_DESIGN_ELEMENTS, ctx)
        assert "ADMIT ONE" in lines
        assert "D7" in lines
        assert "Clockers (1995) [18]" in lines
        assert "[ 18.png ]" in lines
        assert any(line.startswith("[ QR") for line in lines)

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

    def test_feed_lines_clamps_bad_values(self):
        Settings.set("tickets.feed_lines", "oops")
        assert ticket_service.feed_lines() == 2
        Settings.set("tickets.feed_lines", 99)
        assert ticket_service.feed_lines() == 20
        Settings.set("tickets.feed_lines", -5)
        assert ticket_service.feed_lines() == 0
