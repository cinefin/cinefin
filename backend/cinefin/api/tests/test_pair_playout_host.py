import tempfile
from io import StringIO

import pytest
from django.core.management import call_command

from cinefin.api.models import PlayoutHost
from cinefin.api.services import schedule_runner

pytestmark = pytest.mark.django_db

SEEDED_URL = "http://127.0.0.1:8089"


def pair(**kwargs):
    out = StringIO()
    call_command("pair_playout_host", stdout=out, **kwargs)
    return out.getvalue()


class TestPairPlayoutHost:
    def test_adopts_seeded_loopback_row(self):
        assert PlayoutHost.objects.count() == 1
        out = pair(url=SEEDED_URL + "/", token="tok-1")
        assert PlayoutHost.objects.count() == 1
        host = PlayoutHost.objects.get()
        assert host.token == "tok-1"
        assert host.enabled and host.is_active
        assert "Updated" in out

    def test_creates_new_host_and_activates_it(self):
        seeded = PlayoutHost.objects.get()
        out = pair(url="http://htpc:8089", token="tok-2", name="HTPC")
        host = PlayoutHost.objects.get(base_url="http://htpc:8089")
        assert host.name == "HTPC"
        assert host.token == "tok-2"
        assert host.enabled and host.is_active
        assert "Created" in out
        seeded.refresh_from_db()
        assert not seeded.is_active

    def test_name_untouched_on_update_unless_given(self):
        PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089")
        pair(url="http://booth:8089", token="tok-3")
        assert PlayoutHost.objects.get(base_url="http://booth:8089").name == "Booth"

    def test_activation_clears_other_hosts(self):
        other = PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", is_active=True)
        pair(url="http://htpc:8089", token="tok-4", name="HTPC")
        other.refresh_from_db()
        assert not other.is_active
        assert PlayoutHost.objects.filter(is_active=True).count() == 1
        assert PlayoutHost.objects.get(is_active=True).name == "HTPC"

    def test_idempotent(self):
        pair(url="http://htpc:8089", token="tok-5")
        pair(url="http://htpc:8089", token="tok-6")
        assert PlayoutHost.objects.filter(base_url="http://htpc:8089").count() == 1
        host = PlayoutHost.objects.get(base_url="http://htpc:8089")
        assert host.token == "tok-6"
        assert host.is_active


def test_heartbeat_default_is_in_tempdir(settings):
    if hasattr(settings, "SCHEDULER_HEARTBEAT_FILE"):
        delattr(settings, "SCHEDULER_HEARTBEAT_FILE")
    assert schedule_runner.heartbeat_path().startswith(tempfile.gettempdir())
