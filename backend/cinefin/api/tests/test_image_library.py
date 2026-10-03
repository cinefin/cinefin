"""The image libraries (titles, tickets): upload, list, and delete guarded by use."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from cinefin.api.models import ProgrammeTitleTemplate

pytestmark = pytest.mark.django_db

API = "/api/v2/images"


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def _png(name="logo.png"):
    buf = io.BytesIO()
    Image.new("RGB", (4, 3)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def _upload(client, library, name="logo.png"):
    return client.post(f"{API}/{library}", {"file": _png(name)})


@pytest.mark.parametrize("library", ["titles", "tickets"])
def test_upload_list_delete(client, library):
    r = _upload(client, library)
    assert r.status_code == 201 and r.json()["data"]["width"] == 4
    assert _upload(client, library).json()["data"]["name"] == "logo (1).png"  # no clobbering
    assert [i["name"] for i in client.get(f"{API}/{library}").json()["data"]] == ["logo (1).png", "logo.png"]
    assert client.delete(f"{API}/{library}/logo.png").status_code == 200
    assert client.delete(f"{API}/{library}/logo.png").status_code == 404


def test_a_title_image_in_use_is_kept(client):
    url = _upload(client, "titles").json()["data"]["url"]
    ProgrammeTitleTemplate.objects.create(
        name="Evening", template_config={"elements": [{"type": "image", "path": url}]}
    )
    r = client.delete(f"{API}/titles/logo.png")
    assert r.status_code == 409 and "Evening" in str(r.json())


def test_rejects_unknown_library_and_wrong_type(client):
    assert client.get(f"{API}/nope").status_code == 404
    gif = SimpleUploadedFile("a.gif", b"GIF89a", content_type="image/gif")
    assert client.post(f"{API}/titles", {"file": gif}).status_code == 400  # titles take PNG/JPEG only
