import pytest

from cinefin.api.models import AudioTrack, Playlist, SubtitleTrack
from cinefin.api.services.playlist_service import PlaylistService

from .factories import MovieFactory, ProgrammeFactory, block_for

pytestmark = pytest.mark.django_db


def patch_tracks(client, programme_id, block_id, payload):
    url = f"/api/v2/programmes/{programme_id}/blocks/{block_id}/tracks"
    return client.patch(url, data=payload, content_type="application/json")


@pytest.fixture
def feature():
    programme = ProgrammeFactory()
    movie = MovieFactory()
    for idx, language in enumerate(("eng", "fra", "deu")):
        AudioTrack.objects.create(movie=movie, language=language, codec="dts", channels=6, index=idx)
    for idx, language in enumerate(("eng", "nld")):
        SubtitleTrack.objects.create(movie=movie, language=language, index=idx)
    block = block_for(programme, 0, "movie", movie, audio_track_index=0)
    PlaylistService.save_playlist_to_database(programme, PlaylistService.build_playlist_from_programme(programme))
    return programme, block


def tracks(block):
    block.refresh_from_db()
    playback = block.playlist_items.get(content_type="movie").movie_playback
    assert (playback.audio_track_index, playback.subtitle_track_index) == (
        block.audio_track_index,
        block.subtitle_track_index,
    )
    return block.audio_track_index, block.subtitle_track_index


def test_updates_block_and_playback_in_place(client, feature):
    programme, block = feature
    item_ids = set(Playlist.objects.get(programme=programme).items.values_list("id", flat=True))

    response = patch_tracks(client, programme.id, block.id, {"audio_track_index": 2, "subtitle_track_index": 1})
    assert response.json()["data"] == {
        "block_id": block.id,
        "audio_track_index": 2,
        "subtitle_track_index": 1,
        "playlist_items_updated": 1,
    }
    assert tracks(block) == (2, 1)
    assert set(Playlist.objects.get(programme=programme).items.values_list("id", flat=True)) == item_ids

    # A null subtitle turns subtitles off and leaves audio alone.
    assert patch_tracks(client, programme.id, block.id, {"subtitle_track_index": None}).status_code == 200
    assert tracks(block) == (2, None)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"audio_track_index": 7}, "AUDIO_TRACK_OUT_OF_RANGE"),
        ({"subtitle_track_index": 5}, "SUBTITLE_TRACK_OUT_OF_RANGE"),
    ],
)
def test_rejects_index_beyond_the_track_list(client, feature, payload, code):
    programme, block = feature
    response = patch_tracks(client, programme.id, block.id, payload)
    assert response.status_code == 400 and response.json()["error_code"] == code
    assert tracks(block) == (0, None)
