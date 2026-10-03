"""The window titles cinefin gives each file it loads into the player."""

import pytest

from cinefin.api.models import PlaylistItem
from cinefin.api.mpv_controller import title_option
from cinefin.api.mpv_service import item_title

from .factories import BumperFactory


def test_title_option_length_prefixes_the_utf8_bytes():
    assert title_option("Trailer: Amélie, Again") == "force-media-title=%23%Trailer: Amélie, Again"


@pytest.mark.parametrize(
    "kind,metadata,want",
    [
        ("movie", {"movie_title": "Heat"}, "Feature: Heat"),
        ("trailer", {"trailer_title": "Dune"}, "Trailer: Dune"),
        ("bumper", {"bumper_title": "Sponsor"}, "User Media: Sponsor"),
        ("command", {"command_name": "House lights down"}, "Command: House lights down"),
        ("certification", {}, "Certification"),
        ("system", {}, "Black"),
    ],
)
def test_item_title_falls_back_to_what_the_playlist_recorded(kind, metadata, want):
    # No linked content (it was deleted): the name the playlist was built with.
    assert item_title(PlaylistItem(content_type=kind, metadata=metadata)) == want


@pytest.mark.django_db
def test_item_title_prefers_the_linked_content():
    bumper = BumperFactory(title="Coming Soon")
    item = PlaylistItem(content_type="bumper", bumper=bumper, metadata={"bumper_title": "Old name"})
    assert item_title(item) == "User Media: Coming Soon"
