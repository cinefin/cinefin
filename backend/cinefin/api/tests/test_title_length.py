"""The title card's length, as shown on the programme's title tab."""

import pytest

from cinefin.api.models import ProgrammeTitleTemplate
from cinefin.api.services import titlegen_service
from cinefin.api.services.titlegen_service import title_length

from .factories import ProgrammeFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def template():
    return ProgrammeTitleTemplate.objects.create(name="Plain", default_duration=8)


def test_no_title_template_has_no_length():
    assert title_length(ProgrammeFactory()) is None


def test_template_default(template):
    assert title_length(ProgrammeFactory(title_template=template)) == 8


def test_background_video_length(template, monkeypatch):
    monkeypatch.setattr("cinefin.api.ninja_views.media.utils.get_media_duration", lambda path: 21.7)
    programme = ProgrammeFactory(title_template=template, title_background_type="video", title_background_file="bg.mp4")
    assert title_length(programme) == 21


def test_programme_detail_reports_it(client, template):
    programme = ProgrammeFactory(title_template=template)
    data = client.get(f"/api/v2/programmes/{programme.id}").json()["data"]["programme"]
    assert data["title_length"] == 8


def test_generation_uses_the_same_rule(template):
    programme = ProgrammeFactory(title_template=template)
    assert titlegen_service.TitleGenService(programme)._get_duration() == 8
