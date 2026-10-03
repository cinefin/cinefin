"""Title cards: bundled fonts, the preview renders and the card's length."""

import io

import pytest
from PIL import Image

from cinefin.api.models import ProgrammeTitleTemplate
from cinefin.api.services.titlegen_service import title_length

from .factories import ProgrammeFactory

pytestmark = pytest.mark.django_db

CONFIG = {
    "canvas": {"width": 640, "height": 360},
    "elements": [
        {"type": "text", "field": "title", "x": 40, "y": 40, "font": "Oswald", "size": 48, "color": "#FFFFFF"},
        {"type": "poster", "x": 400, "y": 40, "width": 120, "height": 180},
        {"type": "rectangle", "x": 0, "y": 300, "width": 640, "height": 60, "color": "#000000", "opacity": 0.5},
    ],
}


def _png_size(resp):
    assert resp.status_code == 200 and resp["Content-Type"] == "image/png"
    return Image.open(io.BytesIO(resp.content)).size


def test_preview_endpoints_return_png(client):
    resp = client.post("/api/v2/titlegen/preview", {"template_config": CONFIG}, content_type="application/json")
    assert _png_size(resp) == (640, 360)

    template = ProgrammeTitleTemplate.objects.create(name="Listing card", template_config=CONFIG)
    resp = client.get(f"/api/v2/titlegen/templates/{template.id}/preview")
    assert _png_size(resp) == (640, 360)
    assert resp["Cache-Control"] == "private, max-age=86400"
    assert client.get("/api/v2/titlegen/templates/999999/preview").status_code == 404


def test_title_length(client, monkeypatch):
    assert title_length(ProgrammeFactory()) is None
    template = ProgrammeTitleTemplate.objects.create(name="Plain", default_duration=8)
    programme = ProgrammeFactory(title_template=template)
    assert client.get(f"/api/v2/programmes/{programme.id}").json()["data"]["programme"]["title_length"] == 8

    monkeypatch.setattr("cinefin.api.ninja_views.media.utils.get_media_duration", lambda path: 21.7)
    programme = ProgrammeFactory(title_template=template, title_background_type="video", title_background_file="bg.mp4")
    assert title_length(programme) == 21
