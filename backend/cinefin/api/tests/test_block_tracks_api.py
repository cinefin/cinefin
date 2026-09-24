import json

import pytest

from cinefin.api.models import AudioTrack, Playlist, SubtitleTrack
from cinefin.api.services.playlist_service import PlaylistService

from .factories import MovieFactory, ProgrammeFactory, block_for

pytestmark = pytest.mark.django_db

API = "/api/v2"


def patch_tracks(client, programme_id, block_id, payload):
    return client.patch(
        f"{API}/programmes/{programme_id}/blocks/{block_id}/tracks",
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.fixture
def feature():
    programme = ProgrammeFactory()
    movie = MovieFactory(title="Feature One")
    for idx, language in enumerate(("eng", "fra", "deu")):
        AudioTrack.objects.create(movie=movie, language=language, codec="dts", channels=6, index=idx)
    for idx, language in enumerate(("eng", "nld")):
        SubtitleTrack.objects.create(movie=movie, language=language, index=idx)
    block = block_for(programme, 0, "movie", movie, audio_track_index=0)

    items = PlaylistService.build_playlist_from_programme(programme)
    PlaylistService.save_playlist_to_database(programme, items)
    return programme, block, movie


def playback_for(block):
    item = block.playlist_items.filter(content_type="movie").first()
    assert item is not None, "the block generated no playlist item"
    return item.movie_playback


def test_updates_block_and_the_value_playout_reads(client, feature):
    programme, block, _movie = feature
    playlist_before = Playlist.objects.get(programme=programme)
    item_ids_before = set(playlist_before.items.values_list("id", flat=True))

    response = patch_tracks(client, programme.id, block.id, {"audio_track_index": 2, "subtitle_track_index": 1})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "block_id": block.id,
        "audio_track_index": 2,
        "subtitle_track_index": 1,
        "playlist_items_updated": 1,
    }

    block.refresh_from_db()
    assert block.audio_track_index == 2
    assert block.subtitle_track_index == 1

    playback = playback_for(block)
    assert playback.audio_track_index == 2
    assert playback.subtitle_track_index == 1

    playlist_after = Playlist.objects.get(programme=programme)
    assert playlist_after.id == playlist_before.id
    assert set(playlist_after.items.values_list("id", flat=True)) == item_ids_before
    programme.refresh_from_db()
    assert programme.playlist_stale is False


def test_null_subtitle_turns_subtitles_off_leaving_audio_alone(client, feature):
    programme, block, _movie = feature
    patch_tracks(client, programme.id, block.id, {"audio_track_index": 1, "subtitle_track_index": 0})

    response = patch_tracks(client, programme.id, block.id, {"subtitle_track_index": None})
    assert response.status_code == 200

    block.refresh_from_db()
    assert block.audio_track_index == 1
    assert block.subtitle_track_index is None
    playback = playback_for(block)
    assert playback.audio_track_index == 1
    assert playback.subtitle_track_index is None


def test_rejects_index_beyond_the_movies_track_list(client, feature):
    programme, block, _movie = feature

    response = patch_tracks(client, programme.id, block.id, {"audio_track_index": 7})
    assert response.status_code == 400
    assert response.json()["error_code"] == "AUDIO_TRACK_OUT_OF_RANGE"

    response = patch_tracks(client, programme.id, block.id, {"subtitle_track_index": 5})
    assert response.status_code == 400
    assert response.json()["error_code"] == "SUBTITLE_TRACK_OUT_OF_RANGE"

    block.refresh_from_db()
    assert block.audio_track_index == 0
    assert block.subtitle_track_index is None


def test_rejects_a_block_that_is_not_a_feature(client):
    programme = ProgrammeFactory()
    block = block_for(programme, 0, "random_movie")

    response = patch_tracks(client, programme.id, block.id, {"audio_track_index": 0})
    assert response.status_code == 400
    assert response.json()["error_code"] == "BLOCK_NOT_A_FEATURE"


def test_block_from_another_programme_is_not_found(client, feature):
    _programme, block, _movie = feature
    other = ProgrammeFactory()

    response = patch_tracks(client, other.id, block.id, {"audio_track_index": 1})
    assert response.status_code == 404
    assert response.json()["error_code"] == "BLOCK_NOT_FOUND"
