"""Seeded random sort: stable pagination, reshuffles by seed."""

import pytest

from cinefin.api.tests.factories import MovieFactory

pytestmark = pytest.mark.django_db


def test_seeded_random_stable_across_pages_and_varies_by_seed(client):
    for i in range(30):
        MovieFactory(title=f"M{i:02d}", tmdbid=1000 + i)

    def ids(seed, page):
        r = client.get(f"/api/v2/movies/list?sort=random&random_seed={seed}&page={page}&per_page=10")
        return [m["id"] for m in r.json()["data"]["items"]]

    p1, p2, p3 = ids(42, 1), ids(42, 2), ids(42, 3)
    allids = p1 + p2 + p3
    assert len(allids) == 30 and len(set(allids)) == 30  # no dupes/gaps
    assert ids(42, 1) == p1  # stable re-fetch
    assert ids(99, 1) != p1  # different seed reorders
    assert p1 != list(range(1, 11))  # actually shuffled, not id order
