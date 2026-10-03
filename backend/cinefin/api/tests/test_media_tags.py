"""User-media tag tooling: filter, bulk add/remove, tag CRUD, counts."""

import pytest

from cinefin.api.models import Tag

from .factories import BumperFactory, TagFactory

pytestmark = pytest.mark.django_db

API = "/api/v2/media"


def _post(client, path, body, method="post"):
    return getattr(client, method)(f"{API}{path}", data=body, content_type="application/json")


def test_tag_filter_matches_any_selected_and_lists_facets(client):
    action = TagFactory(name="Action", color="#ff0000")
    winter = TagFactory(name="Winter")
    TagFactory(name="Empty")
    BumperFactory(title="Both", tags=[action, winter])
    BumperFactory(title="ActionOnly", tags=[action])
    BumperFactory(title="WinterOnly", tags=[winter])
    BumperFactory(title="Untagged")

    media = client.get(f"{API}/list", {"tags": "Action,Winter"}).json()["data"]["media"]
    assert sorted(m["title"] for m in media) == ["ActionOnly", "Both", "WinterOnly"]  # no duplicates

    filters = client.get(f"{API}/list").json()["data"]["filters"]
    facets = {f["name"]: f for f in filters["tag_facets"]}
    assert (facets["Action"]["count"], facets["Action"]["color"], facets["Empty"]["count"]) == (2, "#ff0000", 0)
    assert set(filters["tags"]) == {"Action", "Empty", "Winter"}
    tags = {t["name"]: t for t in client.get(f"{API}/tags").json()["data"]["tags"]}
    assert tags["Winter"]["count"] == 2


def test_bulk_tag_add_and_remove(client):
    a, b = BumperFactory(), BumperFactory()
    r = _post(client, "/bulk-tag", {"ids": [a.id, b.id, 999999], "tag": "Halloween"})  # add is the default
    assert r.status_code == 200
    data = r.json()["data"]
    assert (data["updated"], data["missing"], data["tag"]["count"]) == (2, [999999], 2)
    assert b.tags.filter(name="Halloween").exists()

    r = _post(client, "/bulk-tag", {"ids": [a.id, b.id], "tag": "Halloween", "action": "remove"})
    assert r.json()["data"]["updated"] == 2
    assert not a.tags.exists()
    assert Tag.objects.filter(name="Halloween").exists()


def test_update_tag(client):
    TagFactory(name="Taken")
    tag = TagFactory(name="Old", color="#111111")
    item = BumperFactory(tags=[tag])

    r = _post(client, f"/tags/{tag.id}", {"name": "Renamed", "color": "#25E88A"}, "put")
    assert r.status_code == 200 and r.json()["data"]["count"] == 1
    assert item.tags.get().name == "Renamed"
    tag.refresh_from_db()
    assert tag.color == "#25e88a"

    r = _post(client, f"/tags/{tag.id}", {"color": ""}, "put")
    assert r.json()["data"]["color"] is None
    assert _post(client, f"/tags/{tag.id}", {"name": "Taken"}, "put").status_code == 409
    assert _post(client, "/tags/999999", {"name": "X"}, "put").status_code == 404


def test_delete_tag_untags_items(client):
    tag = TagFactory(name="Gone")
    item = BumperFactory(tags=[tag])
    assert client.delete(f"{API}/tags/{tag.id}").status_code == 200
    assert not Tag.objects.filter(name="Gone").exists()
    assert item.tags.count() == 0
