import io

import pytest
from PIL import Image

from cinefin.api.services.titlegen_service import BUNDLED_FONTS, TitleGenService, bundled_fonts_dir

pytestmark = pytest.mark.django_db

CONFIG = {
    "canvas": {"width": 640, "height": 360},
    "elements": [
        {"type": "text", "field": "title", "x": 40, "y": 40, "font": "Oswald", "size": 48, "color": "#FFFFFF"},
        {"type": "poster", "x": 400, "y": 40, "width": 120, "height": 180},
        {"type": "rectangle", "x": 0, "y": 300, "width": 640, "height": 60, "color": "#000000", "opacity": 0.5},
    ],
}


class TestBundledFonts:
    def test_all_bundled_fonts_ship_and_load(self):
        for name, filename in BUNDLED_FONTS.items():
            path = bundled_fonts_dir() / filename
            assert path.exists(), f"{name} missing from static/fonts"
            font = TitleGenService._load_font(name, 24)
            assert hasattr(font, "getname"), name


class TestPreviewRender:
    def test_preview_endpoint_returns_png(self, client):
        resp = client.post(
            "/api/v2/titlegen/preview",
            {"template_config": CONFIG},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp["Content-Type"] == "image/png"
        image = Image.open(io.BytesIO(resp.content))
        assert image.size == (640, 360)

    def test_template_thumbnail_endpoint_returns_png(self, client):
        from cinefin.api.models import ProgrammeTitleTemplate

        template = ProgrammeTitleTemplate.objects.create(name="Listing card", template_config=CONFIG)
        resp = client.get(f"/api/v2/titlegen/templates/{template.id}/preview")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "image/png"
        assert resp["Cache-Control"] == "private, max-age=86400"
        image = Image.open(io.BytesIO(resp.content))
        assert image.size == (640, 360)

    def test_template_thumbnail_missing_template_404s(self, client):
        resp = client.get("/api/v2/titlegen/templates/999999/preview")
        assert resp.status_code == 404
