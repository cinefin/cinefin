import importlib
import sys
import textwrap

import pytest
import requests

from cinefin import plugins
from cinefin.api.models import Command, Settings
from cinefin.api.services import command_runner

from .factories import CommandFactory

pytestmark = pytest.mark.django_db


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

    def test_contrib_plugin_is_registered_with_its_source(self, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        provider = plugins.get_provider("echo")
        assert provider is not None
        assert provider.source == "contrib/plugins/echo.py"

    def test_package_plugin_with_relative_import(self, plugin_dir, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "helpers.py").write_text("GREETING = 'hi'\n")
        (pkg / "__init__.py").write_text(
            textwrap.dedent("""
                from cinefin.plugins import CommandProvider, register
                from .helpers import GREETING

                @register
                class Pkg(CommandProvider):
                    id = "pkg"
                    def run(self, config, settings):
                        return True, GREETING, ""
            """)
        )
        assert plugins.get_provider("pkg").run({}, {}) == (True, "hi", "")

    def test_broken_plugins_are_reported_and_skipped(self, plugin_dir):
        plugin_dir("a_syntax.py", "def broken(:\n")
        plugin_dir("b_api.py", ECHO_PLUGIN.replace('id = "echo"', 'id = "future"\n        plugin_api = 99'))
        plugin_dir("c_good.py", ECHO_PLUGIN)
        plugin_dir("d_dupe.py", ECHO_PLUGIN)

        failures = {f["source"]: f["error"] for f in plugins.load_failures()}
        assert set(failures) == {"contrib/plugins/a_syntax.py", "contrib/plugins/b_api.py", "contrib/plugins/d_dupe.py"}
        assert "plugin API 99" in failures["contrib/plugins/b_api.py"]
        assert "already registered" in failures["contrib/plugins/d_dupe.py"]
        assert plugins.get_provider("echo").source == "contrib/plugins/c_good.py"

    def test_half_registered_plugin_is_rolled_back(self, plugin_dir):
        plugin_dir("half.py", textwrap.dedent(ECHO_PLUGIN) + "\nraise RuntimeError('late failure')\n")
        assert plugins.get_provider("echo") is None
        assert "late failure" in plugins.load_failures()[0]["error"]

    def test_underscore_and_test_files_are_ignored(self, plugin_dir):
        plugin_dir("_private.py", "raise RuntimeError('should not import')\n")
        plugin_dir("test_echo.py", "raise RuntimeError('should not import')\n")
        assert plugins.load_failures() == []

    def test_bad_field_type_is_a_load_failure(self, plugin_dir):
        plugin_dir("bad.py", ECHO_PLUGIN.replace('Field("text", required=True)', 'Field("text", type="colour")'))
        assert "unknown type 'colour'" in plugins.load_failures()[0]["error"]


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

    def test_shipped_provider_schemas(self, client):
        by_id = {p["id"]: p for p in client.get("/api/v2/commands/providers").json()["data"]["providers"]}
        ha = by_id["homeassistant"]
        assert (ha["has_suggestions"], ha["has_settings_test"], ha["has_discover"]) == (True, True, True)
        assert [f["key"] for f in ha["settings"]] == ["url", "token"]
        assert by_id["rest"]["has_settings_test"] is False
        assert by_id["rest"]["fields"][0] == {
            "key": "method",
            "label": "Method",
            "type": "select",
            "required": False,
            "default": "GET",
            "placeholder": "",
            "help": "",
            "choices": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "scoped_by": "",
        }

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
        response = client.post(
            "/api/v2/commands/create",
            data={"name": "Broken", "provider": provider, "config": config},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == error_code

    def test_create_validates_json_fields(self, client):
        response = client.post(
            "/api/v2/commands/create",
            data={"name": "Broken", "provider": "rest", "config": {"url": "http://x.invalid/", "headers": "nope"}},
            content_type="application/json",
        )
        assert response.json()["error_code"] == "INVALID_COMMAND_CONFIG"

    def test_create_rejects_a_duplicate_name(self, client):
        client.post(
            "/api/v2/commands/create",
            data={"name": "Dim lights", "provider": "rest", "config": {"url": "http://x.invalid/"}},
            content_type="application/json",
        )
        response = client.post(
            "/api/v2/commands/create",
            data={"name": "Dim lights", "provider": "rest", "config": {"url": "http://y.invalid/"}},
            content_type="application/json",
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "CONFLICT"

    def test_rename_onto_an_existing_name_conflicts(self, client):
        CommandFactory(name="Lights up", provider="rest", config={"url": "http://a.invalid/"})
        other = CommandFactory(name="Lights down", provider="rest", config={"url": "http://b.invalid/"})
        response = client.put(
            f"/api/v2/commands/{other.id}/update",
            data={"name": "Lights up"},
            content_type="application/json",
        )
        assert response.status_code == 409
        # A no-op rename to its own name is fine (excludes self).
        ok = client.put(
            f"/api/v2/commands/{other.id}/update",
            data={"name": "Lights down"},
            content_type="application/json",
        )
        assert ok.status_code == 200

    def test_suggestions_failure_is_a_result_not_an_error(self, client):
        data = client.get("/api/v2/commands/providers/homeassistant/suggestions").json()["data"]
        assert data["ok"] is False
        assert "not configured" in data["message"]

    def test_homeassistant_suggestions_are_scoped(self, client, monkeypatch):
        Settings.set("plugins.homeassistant", {"url": "http://ha.invalid", "token": "t"})

        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self.payload

        payloads = {
            "/api/services": [{"domain": "scene", "services": {"turn_on": {}}}],
            "/api/states": [{"entity_id": "scene.dim", "attributes": {"friendly_name": "Dim"}}],
        }
        monkeypatch.setattr(requests, "get", lambda url, **kw: Resp(payloads[url.removeprefix("http://ha.invalid")]))
        data = client.get("/api/v2/commands/providers/homeassistant/suggestions").json()["data"]
        assert data["ok"] is True
        assert data["suggestions"]["service"] == [{"value": "turn_on", "label": None, "scope": "scene"}]
        assert data["suggestions"]["entity_id"] == [{"value": "scene.dim", "label": "Dim", "scope": "scene"}]

    def test_provider_settings_round_trip(self, client, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        url = "/api/v2/commands/providers/echo/settings"
        assert client.get(url).json()["data"]["values"] == {"prefix": ">"}
        response = client.put(url, data={"values": {"prefix": "!", "undeclared": 1}}, content_type="application/json")
        assert response.status_code == 200
        assert Settings.get("plugins.echo") == {"prefix": "!"}

    def test_settings_rejected_for_provider_without_settings(self, client):
        response = client.put(
            "/api/v2/commands/providers/rest/settings", data={"values": {}}, content_type="application/json"
        )
        assert response.status_code == 400

    def test_settings_test_uses_unsaved_values_over_saved(self, client, monkeypatch):
        Settings.set("plugins.homeassistant", {"url": "http://saved.invalid", "token": "saved"})
        seen = {}

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"location_name": "Home", "version": "2026.9"}

        def fake_get(url, headers, **kw):
            seen.update(url=url, auth=headers["Authorization"])
            return Resp()

        monkeypatch.setattr(requests, "get", fake_get)
        response = client.post(
            "/api/v2/commands/providers/homeassistant/settings/test",
            data={"values": {"token": "typed"}},
            content_type="application/json",
        )
        assert response.json()["data"] == {"ok": True, "message": "Connected to Home (Home Assistant 2026.9)"}
        assert seen == {"url": "http://saved.invalid/api/config", "auth": "Bearer typed"}

    def test_settings_test_unsupported(self, client):
        response = client.post(
            "/api/v2/commands/providers/rest/settings/test", data={"values": {}}, content_type="application/json"
        )
        assert response.json()["error_code"] == "NO_SETTINGS_TEST"

    def test_discover_returns_candidates(self, client, monkeypatch):
        plugins.get_provider("homeassistant")
        discovery = sys.modules["cinefin_contrib_plugins.homeassistant.discovery"]
        monkeypatch.setattr(discovery, "_mdns_discover", lambda: [])
        monkeypatch.setattr(
            discovery, "_probe_fallback", lambda: [{"url": "http://ha:8123", "name": "ha", "version": None}]
        )
        data = client.get("/api/v2/commands/providers/homeassistant/discover").json()["data"]
        assert data["candidates"] == [{"label": "ha", "values": {"url": "http://ha:8123"}}]


class TestEnableDisable:
    def test_provider_defaults_enabled_and_toggle_persists(self, client, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        by_id = {p["id"]: p for p in client.get("/api/v2/commands/providers").json()["data"]["providers"]}
        assert by_id["echo"]["enabled"] is True

        response = client.post(
            "/api/v2/commands/providers/echo/enabled", data={"enabled": False}, content_type="application/json"
        )
        assert response.status_code == 200
        assert plugins.is_enabled("echo") is False
        assert plugins.get_provider("echo").to_dict()["enabled"] is False

        client.post("/api/v2/commands/providers/echo/enabled", data={"enabled": True}, content_type="application/json")
        assert plugins.is_enabled("echo") is True

    def test_disabled_provider_refuses_to_run(self, plugin_dir):
        plugin_dir("echo.py", ECHO_PLUGIN)
        command = CommandFactory(provider="echo", config={"text": "hi"})
        plugins.set_enabled("echo", False)
        result = command_runner.execute(command, trigger="test", wait=True)
        assert result.ok is False
        assert "disabled" in result.detail


class TestWakeOnLan:
    def test_sends_magic_packet(self, monkeypatch):
        sent = {}

        class FakeSocket:
            def __init__(self, *args):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def setsockopt(self, *args):
                pass

            def sendto(self, packet, target):
                sent.update(packet=packet, target=target)

        provider = plugins.get_provider("wake_on_lan")
        monkeypatch.setattr("socket.socket", FakeSocket)
        ok, detail, _ = provider.run({"mac": "AA:BB:CC:DD:EE:FF", "broadcast": "192.168.1.255", "port": 7}, {})
        assert (ok, detail) == (True, "packet sent")
        assert sent["target"] == ("192.168.1.255", 7)
        assert sent["packet"] == b"\xff" * 6 + bytes.fromhex("aabbccddeeff") * 16

    def test_rejects_bad_mac(self):
        ok, detail, _ = plugins.get_provider("wake_on_lan").run({"mac": "nope"}, {})
        assert (ok, detail) == (False, "invalid MAC address")


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
