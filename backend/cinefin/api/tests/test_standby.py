"""Standby: the spec a player is sent, when it is sent, and mpv_service.standby()."""

import hashlib
import os
from unittest.mock import MagicMock

import pytest

from cinefin.api.exceptions import UnprocessableEntityError
from cinefin.api.models import Bumper, PlayoutHost, Settings
from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services import standby
from cinefin.api.services.playout_agent_service import PlayoutAgentService
from cinefin.api.utils.assets import system_ident_path

from .factories import ProgrammeFactory

pytestmark = pytest.mark.django_db


def _own_ident(tmp_path, hold_point=None, content=b"own ident"):
    path = tmp_path / "ident.mp4"
    path.write_bytes(content)
    bumper = Bumper.objects.create(title="Roxy ident", file_path=str(path), hold_point=hold_point)
    Settings.set("cinema.default_ident_id", bumper.id)
    return bumper, path


def _agent(**kw):
    return PlayoutHost.objects.create(
        name=kw.pop("name", "Screen 1"), base_url="http://booth:8089", token="t", agent_id="a", protocol=2, **kw
    )


class TestSpec:
    def test_system_ident_loops_its_hold_range(self):
        Settings.set("cinema.default_ident_id", None)
        Settings.set("cinema.name", "The Roxy")
        spec = standby.standby_spec(_agent(show_status=False))

        assert "/stream/system/ident/?t=" in spec["ident"]["url"]
        assert spec["ident"]["options"] == "ab-loop-a=4,ab-loop-b=34"
        with open(system_ident_path(), "rb") as f:
            assert spec["ident"]["sha256"] == hashlib.sha256(f.read()).hexdigest()
        assert spec["cinema_name"] == "The Roxy"
        assert spec["player_name"] == "Screen 1"
        assert spec["show_status"] is False

    @pytest.mark.parametrize(("hold", "options"), [(None, "keep-open=always"), (12.5, "end=12.5,keep-open=always")])
    def test_own_ident_freezes_on_its_last_frame_or_hold_point(self, tmp_path, hold, options):
        bumper, _ = _own_ident(tmp_path, hold_point=hold)
        ident = standby.standby_spec(_agent())["ident"]
        assert f"/stream/bumper/{bumper.id}/?t=" in ident["url"]
        assert ident["options"] == options
        assert ident["sha256"] == hashlib.sha256(b"own ident").hexdigest()

    @pytest.mark.parametrize("missing", ["file", "item"])
    def test_falls_back_to_the_system_ident(self, tmp_path, missing):
        bumper, path = _own_ident(tmp_path)
        if missing == "file":
            os.remove(path)
        else:
            bumper.delete()
        url, file_path, options, label = standby.resolve_ident()
        assert "/stream/system/ident/" in url and file_path == system_ident_path()
        assert label == "System Ident"


class TestPushTriggers:
    SETTINGS = "/api/v2/settings/"

    def test_cinema_name_ident_and_streaming_url_push(self, client, standby_pushes, tmp_path):
        client.post(self.SETTINGS, data={"subtitle_bold": True}, content_type="application/json")
        assert standby_pushes == []
        client.post(self.SETTINGS, data={"cinema_name": "The Roxy"}, content_type="application/json")
        bumper, _ = _own_ident(tmp_path)
        Settings.set("cinema.default_ident_id", None)
        client.post(self.SETTINGS, data={"default_cinema_ident": bumper.id}, content_type="application/json")
        client.post(self.SETTINGS, data={"playout_server_url": "http://c:8000"}, content_type="application/json")
        assert standby_pushes == [None, None, None]

    def test_the_idents_hold_point_pushes(self, client, standby_pushes, tmp_path):
        bumper, _ = _own_ident(tmp_path)
        other = Bumper.objects.create(title="Sting", file_path="/x.mp4")
        url = "/api/v2/media/{}"
        r = client.put(url.format(bumper.id), data={"hold_point": 9.5}, content_type="application/json")
        assert r.json()["data"]["hold_point"] == 9.5
        client.put(url.format(bumper.id), data={"title": "Renamed"}, content_type="application/json")
        client.put(url.format(other.id), data={"hold_point": 3}, content_type="application/json")
        assert standby_pushes == [None]

        client.put(url.format(bumper.id), data={"hold_point": None}, content_type="application/json")
        bumper.refresh_from_db()
        assert bumper.hold_point is None and standby_pushes == [None, None]

        client.delete(url.format(bumper.id))
        assert standby_pushes == [None, None, None]


class TestSystemIdentChoice:
    """Settings > Playout > Presentation: choosing the System Ident after your own."""

    SETTINGS = "/api/v2/settings/"

    def _save(self, client, **data):
        return client.post(self.SETTINGS, data=data, content_type="application/json")

    def test_choosing_the_system_ident_clears_the_saved_ident_and_pushes_once(self, client, standby_pushes, tmp_path):
        _own_ident(tmp_path)
        # As the settings form sends it: the whole draft, with the System Ident as null.
        assert (
            self._save(client, cinema_name="Cinefin", default_cinema_ident=None, subtitle_bold=False).status_code == 200
        )
        assert Settings.get("cinema.default_ident_id") is None
        assert standby_pushes == [None]
        settings = client.get(self.SETTINGS).json()["data"]["settings"]
        assert settings["default_cinema_ident_id"] is settings["default_cinema_ident"] is None
        self._save(client, default_cinema_ident=None)
        assert standby_pushes == [None]  # choosing it again does not push

    def test_a_deleted_ident_reads_as_the_system_ident(self, client, tmp_path):
        bumper, _ = _own_ident(tmp_path)
        Bumper.objects.filter(id=bumper.id).delete()
        settings = client.get(self.SETTINGS).json()["data"]["settings"]
        assert settings["default_cinema_ident_id"] is settings["default_cinema_ident"] is None
        # So the form's next save (null) goes through instead of failing as not found.
        assert self._save(client, default_cinema_ident=None).status_code == 200


class TestPush:
    def _agent_calls(self, monkeypatch, reply=None):
        calls = []

        def put(cls, host, spec):
            calls.append(("PUT", host.name, spec))
            return reply or {"on_standby": False}

        monkeypatch.setattr(PlayoutAgentService, "put_standby", classmethod(put))
        monkeypatch.setattr(
            PlayoutAgentService, "enter_standby", classmethod(lambda cls, host: calls.append(("POST", host.name)))
        )
        return calls

    def test_sends_each_paired_agent_its_spec_once(self, monkeypatch):
        calls = self._agent_calls(monkeypatch)
        _agent(name="One")
        _agent(name="Two", enabled=False)
        PlayoutHost.objects.create(name="Unpaired", base_url="http://x:8089")

        standby.push_now(None)
        standby.push_now(None)
        assert [(c[0], c[1]) for c in calls] == [("PUT", "One")]
        assert calls[0][2]["player_name"] == "One"

    def test_a_cached_changed_ident_is_put_on_screen(self, monkeypatch, tmp_path):
        calls = self._agent_calls(monkeypatch, reply={"on_standby": True, "downloading": False})
        host = _agent()
        standby.push_now([host.id])
        assert calls[-1] == ("POST", "Screen 1")  # first push: the player may be showing anything

        Settings.set("cinema.name", "Renamed")
        del calls[:]
        standby.push_now([host.id])
        assert [c[0] for c in calls] == ["PUT"]  # same ident: no restart

        _own_ident(tmp_path, hold_point=3)
        del calls[:]
        standby.push_now([host.id])
        assert [c[0] for c in calls] == ["PUT", "POST"]

    def test_an_unreachable_agent_is_retried_next_time(self, monkeypatch):
        def fail(cls, host, spec):
            raise UnprocessableEntityError("down")

        monkeypatch.setattr(PlayoutAgentService, "put_standby", classmethod(fail))
        host = _agent()
        standby.push_now(None)  # no raise
        assert host.id not in standby._pushed


def _service(host):
    service = MPVService()
    service.controller = MagicMock()
    service._lazy_initialized = True
    service._session_restored = True
    service._host = host
    return service


class TestStandbyAgent:
    def _wire(self, monkeypatch, status):
        calls = []

        def put(cls, host, spec):
            calls.append("PUT")
            return {}

        def post(cls, host):
            calls.append("POST")
            return status(host) if callable(status) else status

        monkeypatch.setattr(PlayoutAgentService, "put_standby", classmethod(put))
        monkeypatch.setattr(PlayoutAgentService, "enter_standby", classmethod(post))
        return calls

    def test_sends_the_spec_when_it_changed_then_enters_standby(self, monkeypatch):
        host = _agent()
        spec = standby.standby_spec(host)
        ident = {"sha256": spec["ident"]["sha256"], "options": spec["ident"]["options"]}
        echoed = {"spec": {**spec, "ident": ident}, "file": "/state/idents/x.mp4"}
        calls = self._wire(monkeypatch, echoed)
        service = _service(host)
        service.current_programme = ProgrammeFactory()
        service.manual_items = [{"title": "A", "kind": "url"}]

        assert service.standby() is True
        assert calls == ["PUT", "POST"]
        assert service.idle() and service.programme_state == ProgrammeState.NOT_LOADED
        service.controller.load_file.assert_not_called()  # the player owns standby

        assert service.standby() is True
        assert calls == ["PUT", "POST", "POST"]  # unchanged spec: not sent again

    def test_a_change_made_after_connecting_is_what_the_player_gets(self, monkeypatch):
        # Regression: the service held the row read when it connected, so standby sent the old
        # show_status (and name) back to the player after it was turned off.
        host = _agent(show_status=True)
        sent = []
        monkeypatch.setattr(
            PlayoutAgentService, "put_standby", classmethod(lambda cls, h, spec: sent.append(spec) or {})
        )
        monkeypatch.setattr(PlayoutAgentService, "enter_standby", classmethod(lambda cls, h: {}))
        service = _service(PlayoutHost.objects.get(pk=host.pk))
        standby.sync_spec(host)  # what the player holds

        PlayoutHost.objects.filter(pk=host.pk).update(show_status=False, name="Screen 2")
        standby.sync_spec(PlayoutHost.objects.get(pk=host.pk))  # the PATCH's push
        service.standby()

        assert sent[0]["show_status"] is True
        # Nothing after the change sends the old spec back.
        assert [(s["show_status"], s["player_name"]) for s in sent[1:]] == [(False, "Screen 2")] * (len(sent) - 1)

    @pytest.mark.parametrize("lost", [True, False], ids=["lost-its-spec", "failed-download"])
    def test_the_spec_is_sent_again(self, monkeypatch, lost):
        host = _agent()
        spec = standby.standby_spec(host)
        ident = {"sha256": spec["ident"]["sha256"], "options": spec["ident"]["options"]}
        failed = {"spec": {**spec, "ident": ident}, "file": "", "downloading": False, "error": "404"}
        calls = self._wire(monkeypatch, {"spec": None} if lost else failed)
        if lost:
            standby.sync_spec(host)  # sent earlier, then the player was reset
        assert _service(host).standby() is True
        assert calls == ["PUT", "POST", "PUT", "POST"]


class TestStandbyLocal:
    def _local(self):
        return PlayoutHost.objects.create(name="Local", kind=PlayoutHost.KIND_LOCAL_SOCKET, socket_path="/s")

    def test_a_push_reloads_an_idle_local_mpv_only_when_the_ident_changed(self, tmp_path, monkeypatch):
        from cinefin.api import mpv_service as mpv_mod

        host = self._local()
        PlayoutHost.objects.filter(pk=host.pk).update(is_active=True)
        host.refresh_from_db()
        service = _service(host)
        monkeypatch.setattr(mpv_mod, "mpv_service", service)
        loads = service.controller.load_file

        standby.push_now(None)  # nothing shown yet: load it
        assert loads.call_count == 1

        Settings.set("cinema.name", "Renamed")
        PlayoutHost.objects.filter(pk=host.pk).update(name="Booth", show_status=False)
        standby.push_now(None)
        assert loads.call_count == 1  # same ident and options: no replay

        bumper, _ = _own_ident(tmp_path)
        standby.push_now(None)
        assert loads.call_count == 2  # a new ident

        bumper.hold_point = 4
        bumper.save()
        standby.push_now(None)
        assert loads.call_count == 3  # same file, new options
        assert loads.call_args.kwargs["options"] == "end=4,keep-open=always"

        service.current_programme = ProgrammeFactory()
        bumper.hold_point = 6
        bumper.save()
        standby.push_now(None)
        assert loads.call_count == 3  # never over a loaded programme

    def test_loads_the_ident_with_its_hold_and_plays(self, tmp_path):
        bumper, _ = _own_ident(tmp_path, hold_point=5)
        service = _service(self._local())
        assert service.standby() is True
        service.controller.load_file.assert_called_once_with(
            bumper.get_stream_url()["stream_url"],
            replace=True,
            options="end=5,keep-open=always",
            title="System Ident",
        )
        service.controller.pause.assert_called_once_with(False)

    @pytest.mark.parametrize(("version", "warned"), [("mpv 0.37.0", True), ("mpv v0.41.0", False), (None, False)])
    def test_old_mpv_is_flagged(self, version, warned):
        service = _service(self._local())
        service.controller.transport = ("socket", "/s", None)
        service.controller.get_property.return_value = version
        service._check_mpv_version()
        assert bool(service.player_warning) is warned


class TestPreviewStandby:
    URL = "/api/v2/settings/preview-standby/"

    def test_calls_standby_unless_a_programme_is_loaded(self, client, monkeypatch):
        from cinefin.api.mpv_service import mpv_service

        monkeypatch.setattr(mpv_service, "standby", MagicMock(return_value=True))
        assert client.post(self.URL).status_code == 200
        mpv_service.standby.assert_called_once_with()
        monkeypatch.setattr(mpv_service, "current_programme", ProgrammeFactory())
        assert client.post(self.URL).status_code == 409
        assert mpv_service.standby.call_count == 1
