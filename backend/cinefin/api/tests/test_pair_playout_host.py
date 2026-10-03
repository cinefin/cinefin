import tempfile
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cinefin.api.exceptions import ValidationError
from cinefin.api.models import PlayoutHost
from cinefin.api.services import schedule_runner
from cinefin.api.services.playout_agent_service import PlayoutAgentService

pytestmark = pytest.mark.django_db

SEEDED_URL = "http://127.0.0.1:8089"


def pair(answer=None, **kwargs):
    """Run the command with the agent's /pair answer stubbed."""
    answer = answer or {"token": "tok", "id": "", "name": "Player"}
    out = StringIO()
    with patch.object(PlayoutAgentService, "pair", return_value=answer) as agent_pair:
        call_command("pair_playout_host", stdout=out, **kwargs)
    agent_pair.assert_called_once_with(kwargs["url"].strip().rstrip("/"), kwargs["code"])
    return out.getvalue()


class TestPairPlayoutHost:
    def test_fresh_install_has_no_placeholder_host(self):
        # 0019 seeds one; 0048 drops it again while it is still untouched.
        assert PlayoutHost.objects.count() == 0

    def test_adopts_a_host_at_the_same_url(self):
        PlayoutHost.objects.create(name="Playout host", base_url=SEEDED_URL)
        out = pair({"token": "tok-1", "id": "a1", "name": "Box"}, url=SEEDED_URL + "/", code="123456")
        assert PlayoutHost.objects.count() == 1
        host = PlayoutHost.objects.get()
        assert host.token == "tok-1" and host.agent_id == "a1"
        assert host.enabled and host.is_active
        assert "Re-paired" in out

    def test_creates_new_host_and_activates_it(self):
        seeded = PlayoutHost.objects.create(name="Other", base_url=SEEDED_URL, is_active=True)
        out = pair({"token": "tok-2", "id": "b2", "name": "htpc"}, url="http://htpc:8089", code="1", name="HTPC")
        host = PlayoutHost.objects.get(base_url="http://htpc:8089")
        assert host.name == "HTPC"
        assert host.token == "tok-2"
        assert host.enabled and host.is_active
        assert "Paired new" in out
        seeded.refresh_from_db()
        assert not seeded.is_active

    def test_new_host_takes_the_players_name(self):
        pair({"token": "t", "id": "c3", "name": "living-room"}, url="http://lr:8089", code="1")
        assert PlayoutHost.objects.get(base_url="http://lr:8089").name == "living-room"

    def test_name_untouched_on_repair_unless_given(self):
        PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089")
        pair({"token": "t", "id": "d4", "name": "other"}, url="http://booth:8089", code="1")
        assert PlayoutHost.objects.get(base_url="http://booth:8089").name == "Booth"

    def test_matches_by_agent_id_when_the_address_changed(self):
        PlayoutHost.objects.create(name="Booth", base_url="http://old:8089", agent_id="e5")
        pair({"token": "t2", "id": "e5", "name": "x"}, url="http://new:8089", code="1")
        host = PlayoutHost.objects.get(agent_id="e5")
        assert host.base_url == "http://new:8089" and host.token == "t2"
        assert PlayoutHost.objects.filter(agent_id="e5").count() == 1

    def test_wrong_code_is_a_command_error(self):
        with (
            patch.object(PlayoutAgentService, "pair", side_effect=ValidationError("That code is not right.")),
            pytest.raises(CommandError, match="not right"),
        ):
            call_command("pair_playout_host", url="http://htpc:8089", code="000000", stdout=StringIO())


def test_heartbeat_default_is_in_tempdir(settings):
    if hasattr(settings, "SCHEDULER_HEARTBEAT_FILE"):
        delattr(settings, "SCHEDULER_HEARTBEAT_FILE")
    assert schedule_runner.heartbeat_path().startswith(tempfile.gettempdir())
