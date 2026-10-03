"""The `cinefin` command: data folder, listen address, public URL, precedence, info."""

import argparse
import os

import pytest

from cinefin import cli

ENV_VARS = [
    "CINEFIN_USERDATA_DIR",
    "CINEFIN_HOST",
    "CINEFIN_PORT",
    "CINEFIN_SERVER_URL",
    "CINEFIN_LOG_LEVEL",
    "CINEFIN_LOG_FILE",
    "SQLITE_PATH",
    "CINEFIN_USERMEDIA_DIR",
    "XDG_DATA_HOME",
    "LOCALAPPDATA",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.setenv(var, "x")  # so the delete below is recorded and undone
        monkeypatch.delenv(var)
    monkeypatch.setattr(cli, "lan_address", lambda: "192.168.1.50")


def _checkout(tmp_path):
    backend = tmp_path / "repo" / "backend"
    backend.mkdir(parents=True)
    (backend / "manage.py").touch()
    (backend / "pyproject.toml").touch()
    return backend


def _args(argv):
    return cli.build_parser().parse_args(["info", *argv])


def test_data_dir_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "BACKEND_DIR", _checkout(tmp_path))
    assert cli.resolve_data_dir() == (tmp_path / "repo" / "userdata", "source checkout")
    monkeypatch.setenv("CINEFIN_USERDATA_DIR", str(tmp_path / "env"))
    assert cli.resolve_data_dir() == (tmp_path / "env", "CINEFIN_USERDATA_DIR")
    assert cli.resolve_data_dir(str(tmp_path / "flag")) == (tmp_path / "flag", "--data-dir")


def test_data_dir_wheel_install_uses_platform_folder(tmp_path, monkeypatch):
    site_packages = tmp_path / "site-packages"  # no manage.py next to the package
    site_packages.mkdir()
    monkeypatch.setattr(cli, "BACKEND_DIR", site_packages)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert cli.resolve_data_dir() == (tmp_path / "xdg" / "cinefin", "platform default")

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert cli.resolve_data_dir() == (tmp_path / "local" / "Cinefin", "platform default")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("127.0.0.1:8000", ("127.0.0.1", 8000)),
        ("[::1]:9000", ("::1", 9000)),
        ("9000", ("0.0.0.0", 9000)),
    ],
)
def test_parse_listen(value, expected):
    assert cli.parse_listen(value) == expected


@pytest.mark.parametrize("value", ["host:abc", "host:70000", "host:"])
def test_parse_listen_rejects(value):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_listen(value)


def test_defaults_then_env(monkeypatch):
    cfg = cli.resolve(_args([]))
    assert cfg["listen"] == ("0.0.0.0:8000", "default")
    assert cfg["public URL"] == ("http://192.168.1.50:8000", "LAN address")
    assert cfg["log file"] == ("", "off")
    monkeypatch.setenv("CINEFIN_HOST", "127.0.0.1")
    monkeypatch.setenv("CINEFIN_PORT", "9001")
    monkeypatch.setenv("CINEFIN_LOG_LEVEL", "DEBUG")
    cfg = cli.resolve(_args([]))
    assert cfg["listen"] == ("127.0.0.1:9001", "CINEFIN_HOST/CINEFIN_PORT")
    assert cfg["public URL"] == ("http://127.0.0.1:9001", "listen address")
    assert cfg["log level"] == ("DEBUG", "CINEFIN_LOG_LEVEL")


def test_flags_beat_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CINEFIN_USERDATA_DIR", str(tmp_path / "env"))
    monkeypatch.setenv("CINEFIN_HOST", "127.0.0.1")
    monkeypatch.setenv("CINEFIN_PORT", "9001")
    monkeypatch.setenv("CINEFIN_SERVER_URL", "http://env.example")
    monkeypatch.setenv("CINEFIN_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CINEFIN_LOG_FILE", "/env.log")
    cfg = cli.resolve(
        _args(
            [
                *("--data-dir", str(tmp_path / "flag")),
                *("--listen", "[::]:8123"),
                *("--public-url", "http://flag.example"),
                *("--log-level", "warning"),
                *("--log-file", "/flag.log"),
            ]
        )
    )
    assert cfg["data folder"] == (str(tmp_path / "flag"), "--data-dir")
    assert cfg["database"] == (str(tmp_path / "flag" / "db.sqlite3"), "data folder")
    assert cfg["listen"] == ("[::]:8123", "--listen")
    assert cfg["public URL"] == ("http://flag.example", "--public-url")
    assert cfg["log level"] == ("WARNING", "--log-level")
    assert cfg["log file"] == ("/flag.log", "--log-file")


def test_apply_env_hands_values_to_django(tmp_path):
    cfg = cli.resolve(_args(["--data-dir", str(tmp_path / "d"), "--listen", "[::]:8123"]))
    cli.apply_env(cfg)
    assert os.environ["CINEFIN_USERDATA_DIR"] == str(tmp_path / "d")
    assert (os.environ["CINEFIN_HOST"], os.environ["CINEFIN_PORT"]) == ("::", "8123")
    assert os.environ["CINEFIN_SERVER_URL"] == "http://192.168.1.50:8123"
    assert "CINEFIN_LOG_FILE" not in os.environ
    assert (tmp_path / "d").is_dir()


def test_info_output(tmp_path, capsys):
    assert cli.main(["info", "--data-dir", str(tmp_path), "--listen", "127.0.0.1:9123"]) == 0
    out = capsys.readouterr().out
    rows = {line[2:15].strip(): line for line in out.splitlines() if line.startswith("  ")}
    assert str(tmp_path) in rows["data folder"] and "(--data-dir)" in rows["data folder"]
    assert "http://127.0.0.1:9123" in rows["public URL"] and "(listen address)" in rows["public URL"]
