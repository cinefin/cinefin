"""User-media tag tooling: filter, bulk add/remove, tag CRUD, counts."""

import pytest

from cinefin.api.models import Tag

from .factories import BumperFactory, TagFactory

pytestmark = pytest.mark.django_db

API = "/api/v2"


def _tag(name, color=""):
    return TagFactory(name=name, color=color)


def test_multi_tag_filter_matches_any_selected(client):
    action = _tag("Action")
    winter = _tag("Winter")

    BumperFactory(title="Both", tags=[action, winter])
    BumperFactory(title="ActionOnly", tags=[action])
    BumperFactory(title="WinterOnly", tags=[winter])
    BumperFactory(title="Untagged")

    resp = client.get(f"{API}/media/list", {"tags": "Action,Winter"})
    assert resp.status_code == 200
    titles = {m["title"] for m in resp.json()["data"]["media"]}
    assert titles == {"Both", "ActionOnly", "WinterOnly"}
    ids = [m["id"] for m in resp.json()["data"]["media"]]
    assert len(ids) == len(set(ids))


def test_single_tag_filter_still_works(client):
    action = _tag("Action")
    BumperFactory(title="A", tags=[action])
    BumperFactory(title="Untagged")

    resp = client.get(f"{API}/media/list", {"tags": "Action"})
    assert resp.status_code == 200
    assert [m["title"] for m in resp.json()["data"]["media"]] == ["A"]


def test_list_media_returns_tag_facets_with_counts_and_colour(client):
    action = _tag("Action", color="#ff0000")
    _tag("Empty")
    BumperFactory(tags=[action])
    BumperFactory(tags=[action])

    resp = client.get(f"{API}/media/list")
    facets = {f["name"]: f for f in resp.json()["data"]["filters"]["tag_facets"]}
    assert facets["Action"]["count"] == 2
    assert facets["Action"]["color"] == "#ff0000"
    assert facets["Empty"]["count"] == 0
    assert set(resp.json()["data"]["filters"]["tags"]) == {"Action", "Empty"}


def test_list_tags_returns_counts(client):
    action = _tag("Action")
    BumperFactory(tags=[action])

    resp = client.get(f"{API}/media/tags")
    assert resp.status_code == 200
    tags = {t["name"]: t for t in resp.json()["data"]["tags"]}
    assert tags["Action"]["count"] == 1


def test_bulk_tag_add(client):
    a = BumperFactory()
    b = BumperFactory()

    resp = client.post(
        f"{API}/media/bulk-tag",
        data={"ids": [a.id, b.id], "tag": "Halloween", "action": "add"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["updated"] == 2
    assert body["missing"] == []
    assert body["tag"]["count"] == 2
    assert a.tags.filter(name="Halloween").exists()
    assert b.tags.filter(name="Halloween").exists()


def test_bulk_tag_add_defaults_to_add_and_creates_tag(client):
    a = BumperFactory()
    resp = client.post(
        f"{API}/media/bulk-tag",
        data={"ids": [a.id], "tag": "Fresh"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert Tag.objects.filter(name="Fresh").exists()
    assert a.tags.filter(name="Fresh").exists()


def test_bulk_tag_remove(client):
    tag = _tag("Christmas")
    a = BumperFactory(tags=[tag])
    b = BumperFactory(tags=[tag])

    resp = client.post(
        f"{API}/media/bulk-tag",
        data={"ids": [a.id, b.id], "tag": "Christmas", "action": "remove"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated"] == 2
    assert not a.tags.filter(name="Christmas").exists()
    assert not b.tags.filter(name="Christmas").exists()
    assert Tag.objects.filter(name="Christmas").exists()


def test_bulk_tag_reports_missing_ids(client):
    a = BumperFactory()
    resp = client.post(
        f"{API}/media/bulk-tag",
        data={"ids": [a.id, 999999], "tag": "T", "action": "add"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["missing"] == [999999]
    assert resp.json()["data"]["updated"] == 1


def test_bulk_tag_rejects_empty_ids(client):
    resp = client.post(
        f"{API}/media/bulk-tag",
        data={"ids": [], "tag": "T", "action": "add"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_bulk_tag_rejects_bad_action(client):
    a = BumperFactory()
    resp = client.post(
        f"{API}/media/bulk-tag",
        data={"ids": [a.id], "tag": "T", "action": "toggle"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_create_tag(client):
    resp = client.post(
        f"{API}/media/tags",
        data={"name": "New", "color": "#3A7BFF"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["color"] == "#3a7bff"
    assert Tag.objects.filter(name="New").exists()


def test_create_tag_rejects_duplicate(client):
    _tag("Dup")
    resp = client.post(
        f"{API}/media/tags",
        data={"name": "Dup"},
        content_type="application/json",
    )
    assert resp.status_code == 409


def test_create_tag_rejects_bad_colour(client):
    resp = client.post(
        f"{API}/media/tags",
        data={"name": "X", "color": "red"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_rename_tag_updates_all_items(client):
    tag = _tag("Old")
    a = BumperFactory(tags=[tag])

    resp = client.put(
        f"{API}/media/tags/{tag.id}",
        data={"name": "Renamed"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    tag.refresh_from_db()
    assert tag.name == "Renamed"
    assert a.tags.filter(name="Renamed").exists()
    assert resp.json()["data"]["count"] == 1


def test_recolour_tag(client):
    tag = _tag("C", color="#111111")
    resp = client.put(
        f"{API}/media/tags/{tag.id}",
        data={"color": "#25E88A"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    tag.refresh_from_db()
    assert tag.color == "#25e88a"


def test_clear_tag_colour(client):
    tag = _tag("C", color="#111111")
    resp = client.put(
        f"{API}/media/tags/{tag.id}",
        data={"color": ""},
        content_type="application/json",
    )
    assert resp.status_code == 200
    tag.refresh_from_db()
    assert tag.color == ""
    assert resp.json()["data"]["color"] is None


def test_rename_tag_rejects_collision(client):
    _tag("Taken")
    tag = _tag("Mine")
    resp = client.put(
        f"{API}/media/tags/{tag.id}",
        data={"name": "Taken"},
        content_type="application/json",
    )
    assert resp.status_code == 409


def test_delete_tag_untags_items(client):
    tag = _tag("Gone")
    a = BumperFactory(tags=[tag])

    resp = client.delete(f"{API}/media/tags/{tag.id}")
    assert resp.status_code == 200
    assert not Tag.objects.filter(name="Gone").exists()
    a.refresh_from_db()
    assert a.tags.count() == 0


def test_update_missing_tag_404(client):
    resp = client.put(
        f"{API}/media/tags/999999",
        data={"name": "X"},
        content_type="application/json",
    )
    assert resp.status_code == 404
