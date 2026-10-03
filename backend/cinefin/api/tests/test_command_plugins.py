import importlib
import textwrap
from unittest.mock import MagicMock

import pytest
import requests

from cinefin import plugins
from cinefin.api.models import Command, Settings
from cinefin.api.services import command_runner

from .factories import CommandFactory

pytestmark = pytest.mark.django_db


def post(client, url, body):
    return client.post(url, data=body, content_type="application/json")


def put(client, url, body):
    return client.put(url, data=body, content_type="application/json")


def fake_json(payload):
    return MagicMock(json=MagicMock(return_value=payload))


@pytest.fixture(autouse=True)
def fresh_registry():
    plugins._reset_for_tests()
    yield
    plugins._reset_for_tests()


@pytest.fixture
def plugin_dir(tmp_path, settings):
    settings.CINEFIN_PLUGINS_DIR = tmp_path

    def write(name, source):
        (tmp_path / name).write_text(textwrap.dedent(source))

    return write


ECHO_PLUGIN = """
    from cinefin.plugins import CommandProvider, Field, register

    @register
    class Echo(CommandProvider):
        id = "echo"
        label = "Echo"
        fields = [Field("text", required=True), Field("mode", type="select", choices=("loud", "quiet"))]
        settings = [Field("prefix", default=">")]

        def run(self, config, settings):
            return True, "echoed", settings["prefix"] + config["text"]

        def summary(self, config):
            return config.get("text", "")
"""


class TestLoader:
    def test_shipped_contrib_plugins_all_load(self):
        # CI guard for contrib PRs: every plugin in the repo imports and registers cleanly.
        assert plugins.load_failures() == []
        assert {"homeassistant", "rest", "wake_on_lan"} <= {p.id for p in plugins.list_providers()}
        assert plugins.get_provider("homeassistant").source == "contrib/plugins/homeassistant"

    def test_broken_plugins_are_reported_and_skipped(self, plugin_dir):
        plugin_dir("a_syntax.py", "def broken(:\n")
        plugin_dir("b_api.py", ECHO_PLUGIN.replace('id = "echo"', 'id = "future"\n        plugin_api = 99'))
        plugin_dir("c_good.py", ECHO_PLUGIN)
        plugin_dir("d_dupe.py", ECHO_PLUGIN)
        plugin_dir(
            "e_badfield.py", ECHO_PLUGIN.replace('id = "echo"', 'id = "bad"').replace("required=True", 'type="colour"')
        )
        plugin_dir("_private.py", "raise RuntimeError('should not import')\n")
        plugin_dir("test_echo.py", "raise RuntimeError('should not import')\n")

        failures = {f["source"]: f["error"] for f in plugins.load_failures()}
        assert set(failures) == {f"contrib/plugins/{n}.py" for n in ("a_syntax", "b_api", "d_dupe", "e_badfield")}
        assert "unknown type 'colour'" in failures["contrib/plugins/e_badfield.py"]
        assert "plugin API 99" in failures["contrib/plugins/b_api.py"]
        assert "already registered" in failures["contrib/plugins/d_dupe.py"]
        assert plugins.get_provider("echo").source == "contrib/plugins/c_good.py"


class TestRunner:
    def test_contrib_provider_runs_with_its_settings(self, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        command = CommandFactory(provider="echo", config={"text": "hello"})
        result = command_runner.execute(command, trigger="test", wait=True)
        assert (result.ok, result.detail, result.output) == (True, "echoed", ">hello")

        Settings.set("plugins.echo", {"prefix": "# "})
        assert command_runner.execute(command, trigger="test", wait=True).output == "# hello"

    def test_misbehaving_provider_never_raises(self, plugin_dir):
        plugin_dir(
            "odd.py",
            """
            from cinefin.plugins import CommandProvider, register

            @register
            class Odd(CommandProvider):
                id = "odd"
                def run(self, config, settings):
                    return "not a tuple"
            """,
        )
        result = command_runner.execute(Command(name="x", provider="odd"), trigger="test", wait=True)
        assert result.ok is False
        assert result.detail.startswith("internal error")


class TestProvidersAPI:
    def test_list_providers_exposes_fields_and_failures(self, client, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        plugin_dir("zz_broken.py", "import does_not_exist\n")
        data = client.get("/api/v2/commands/providers").json()["data"]
        assert data["providers"][0]["id"] == "echo"
        assert data["providers"][0]["settings"][0]["key"] == "prefix"
        assert data["failures"][0]["source"] == "contrib/plugins/zz_broken.py"

    def test_command_list_carries_provider_label_and_summary(self, client, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        CommandFactory(name="A", provider="echo", config={"text": "hi"})
        CommandFactory(name="B", provider="gone", config={})
        commands = {c["name"]: c for c in client.get("/api/v2/commands/list").json()["data"]["commands"]}
        assert (commands["A"]["provider_label"], commands["A"]["summary"]) == ("Echo", "hi")
        assert (commands["B"]["provider_label"], commands["B"]["provider_icon"]) == ("gone", "zap")

    @pytest.mark.parametrize(
        ("provider", "config", "error_code"),
        [
            ("carrier_pigeon", {}, "UNKNOWN_PROVIDER"),
            ("echo", {}, "INVALID_COMMAND_CONFIG"),
            ("echo", {"text": "x", "mode": "shouty"}, "INVALID_COMMAND_CONFIG"),
        ],
    )
    def test_create_validates_against_provider_fields(self, client, plugin_dir, provider, config, error_code):
        plugin_dir("echo.py", ECHO_PLUGIN)
        response = post(client, "/api/v2/commands/create", {"name": "Broken", "provider": provider, "config": config})
        assert response.status_code == 400
        assert response.json()["error_code"] == error_code

    def test_names_are_unique_and_json_fields_validated(self, client):
        body = {"name": "Broken", "provider": "rest", "config": {"url": "http://x.invalid/", "headers": "nope"}}
        assert post(client, "/api/v2/commands/create", body).json()["error_code"] == "INVALID_COMMAND_CONFIG"
        rest = {"provider": "rest", "config": {"url": "http://x.invalid/"}}
        assert post(client, "/api/v2/commands/create", {"name": "Dim lights", **rest}).status_code == 201
        response = post(client, "/api/v2/commands/create", {"name": "Dim lights", **rest})
        assert response.status_code == 409 and response.json()["error_code"] == "CONFLICT"
        other = CommandFactory(name="Lights down", **rest)
        url = f"/api/v2/commands/{other.id}/update"
        assert put(client, url, {"name": "Dim lights"}).status_code == 409
        assert put(client, url, {"name": "Lights down"}).status_code == 200  # its own name is fine

    def test_provider_settings_round_trip(self, client, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        url = "/api/v2/commands/providers/echo/settings"
        assert client.get(url).json()["data"]["values"] == {"prefix": ">"}
        assert put(client, url, {"values": {"prefix": "!", "undeclared": 1}}).status_code == 200
        assert Settings.get("plugins.echo") == {"prefix": "!"}

    def test_settings_test_uses_unsaved_values_over_saved(self, client, monkeypatch):
        Settings.set("plugins.homeassistant", {"url": "http://saved.invalid", "token": "saved"})
        seen = {}

        def fake_get(url, headers, **kw):
            seen.update(url=url, auth=headers["Authorization"])
            return fake_json({"location_name": "Home", "version": "2026.9"})

        monkeypatch.setattr(requests, "get", fake_get)
        response = post(
            client, "/api/v2/commands/providers/homeassistant/settings/test", {"values": {"token": "typed"}}
        )
        assert response.json()["data"] == {"ok": True, "message": "Connected to Home (Home Assistant 2026.9)"}
        assert seen == {"url": "http://saved.invalid/api/config", "auth": "Bearer typed"}


def test_disabled_provider_refuses_to_run(client, plugin_dir):
    plugin_dir("echo.py", ECHO_PLUGIN)
    by_id = {p["id"]: p for p in client.get("/api/v2/commands/providers").json()["data"]["providers"]}
    assert by_id["echo"]["enabled"] is True
    assert post(client, "/api/v2/commands/providers/echo/enabled", {"enabled": False}).status_code == 200
    result = command_runner.execute(CommandFactory(provider="echo", config={"text": "hi"}), trigger="test", wait=True)
    assert result.ok is False and "disabled" in result.detail


class TestWakeOnLan:
    def test_sends_magic_packet(self, monkeypatch):
        sock = MagicMock()
        monkeypatch.setattr("socket.socket", lambda *a: sock)
        sock.__enter__.return_value = sock
        provider = plugins.get_provider("wake_on_lan")
        ok, detail, _ = provider.run({"mac": "AA:BB:CC:DD:EE:FF", "broadcast": "192.168.1.255", "port": 7}, {})
        assert (ok, detail) == (True, "packet sent")
        sock.sendto.assert_called_once_with(b"\xff" * 6 + bytes.fromhex("aabbccddeeff") * 16, ("192.168.1.255", 7))
        assert provider.run({"mac": "nope"}, {})[:2] == (False, "invalid MAC address")


class TestSettingsMigration:
    def test_homeassistant_connection_moves_to_plugin_settings(self):
        from django.apps import apps

        migration = importlib.import_module("cinefin.api.migrations.0039_move_homeassistant_settings_to_plugins")
        row = Settings._get_instance()
        row.data = {"cinema": {"name": "X"}, "integrations": {"homeassistant": {"url": "http://ha", "token": "t"}}}
        row.save()

        migration.forwards(apps, None)

        row.refresh_from_db()
        assert "integrations" not in row.data
        assert row.data["plugins"]["homeassistant"] == {"url": "http://ha", "token": "t"}
        assert row.data["cinema"] == {"name": "X"}


class TestSystemProvider:
    def test_restart_player_calls_the_agent(self, monkeypatch):
        from cinefin.api.services.playout_agent_service import playout_agent_service

        calls = []
        monkeypatch.setattr(playout_agent_service, "restart_mpv", lambda: calls.append(True) or {})
        ok, message, _ = plugins.get_provider("system").run({"action": "Restart the player"}, {})
        assert ok is True and calls == [True] and message == "player restarted"

    @pytest.mark.parametrize(
        ("action", "method"),
        [("Standby", "standby"), ("Stop the programme", "pause"), ("Pause", "pause"), ("Resume", "play")],
    )
    def test_playout_actions_call_the_player(self, monkeypatch, action, method):
        from cinefin.api import mpv_service as mpv_mod

        calls = []
        monkeypatch.setattr(mpv_mod.mpv_service, method, lambda: calls.append(method) or True)
        ok, _, _ = plugins.get_provider("system").run({"action": action}, {})
        assert ok is True and calls == [method]


class TestBuiltinCommands:
    ACTIONS = {"Restart the player", "Standby", "Stop the programme", "Pause", "Resume"}

    def _system(self):
        return Command.objects.filter(provider="system")

    def test_present_after_migrate_and_idempotent(self):
        assert set(self._system().values_list("name", flat=True)) == self.ACTIONS
        plugins.ensure_builtin_commands()
        assert self._system().count() == len(self.ACTIONS)

    def test_the_old_reset_command_becomes_standby_in_place(self):
        from importlib import import_module

        from django.apps import apps

        self._system().filter(name="Standby").delete()
        old = Command.objects.create(
            name="Reset to the idle ident", provider="system", config={"action": "Reset to the idle ident"}, duration=3
        )
        import_module("cinefin.api.migrations.0049_standby").rename_reset_command(apps, None)
        plugins.ensure_builtin_commands()

        standby = self._system().get(name="Standby")
        assert standby.id == old.id and standby.config == {"action": "Standby"} and standby.duration == 3
        assert set(self._system().values_list("name", flat=True)) == self.ACTIONS

    def test_locked_against_delete_rename_reconfigure_and_create(self, client):
        by_name = {c["name"]: c for c in client.get("/api/v2/commands/list").json()["data"]["commands"]}
        assert by_name["Pause"]["locked"] is True
        cmd = self._system().get(name="Pause")
        assert client.delete(f"/api/v2/commands/{cmd.id}/delete").status_code == 409
        url = f"/api/v2/commands/{cmd.id}/update"
        assert client.put(url, {"name": "Hold"}, content_type="application/json").status_code == 400
        assert client.put(url, {"config": {"action": "Resume"}}, content_type="application/json").status_code == 400
        assert client.put(url, {"duration": 5}, content_type="application/json").status_code == 200
        cmd.refresh_from_db()
        assert cmd.name == "Pause" and cmd.duration == 5
        body = {"name": "Another pause", "provider": "system", "config": {"action": "Pause"}}
        assert client.post("/api/v2/commands/create", body, content_type="application/json").status_code == 400
