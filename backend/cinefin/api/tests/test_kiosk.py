import importlib

import pytest
from django.apps import apps

from cinefin.api.models import Settings

pytestmark = pytest.mark.django_db

SETTINGS = "/api/v2/settings/"


def test_old_kiosk_settings_map_onto_the_new_ones():
    Settings.objects.update_or_create(
        id=1,
        defaults={"data": {"kiosk": {"layout": "board", "countdown_minutes": 25, "takeover": True, "clock": False}}},
    )
    importlib.import_module("cinefin.api.migrations.0056_kiosk_settings").forwards(apps, None)
    assert Settings.objects.get(id=1).data["kiosk"] == {"between": "week", "doors_minutes": 20, "clock": False}


def test_kiosk_settings_save_and_reach_the_display(client):
    response = client.post(
        SETTINGS,
        data={"kiosk_between": "films", "kiosk_rotate_seconds": 30, "kiosk_doors_minutes": 15},
        content_type="application/json",
    )
    assert response.status_code == 200
    shown = client.get("/api/v2/kiosk/display").json()["data"]["settings"]
    assert (shown["between"], shown["rotate_seconds"], shown["doors_minutes"]) == ("films", 30, 15)


def test_unknown_between_screenings_option_is_refused(client):
    response = client.post(SETTINGS, data={"kiosk_between": "wall"}, content_type="application/json")
    assert response.status_code == 400
