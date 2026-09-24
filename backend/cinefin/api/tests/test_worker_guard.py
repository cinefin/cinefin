import pytest
from django.core.exceptions import ImproperlyConfigured

from cinefin.api.apps import ApiConfig


def _run_guard(monkeypatch, argv, cmd_args=""):
    monkeypatch.setattr("sys.argv", argv)
    if cmd_args:
        monkeypatch.setenv("GUNICORN_CMD_ARGS", cmd_args)
    else:
        monkeypatch.delenv("GUNICORN_CMD_ARGS", raising=False)
    ApiConfig._assert_single_web_worker()


@pytest.mark.parametrize(
    "argv",
    [
        ["/usr/bin/gunicorn", "cinefin.wsgi:application", "--workers", "1", "--threads", "4"],
        ["/usr/bin/gunicorn", "cinefin.wsgi:application", "--workers=1"],
        ["/usr/bin/gunicorn", "cinefin.wsgi:application", "-w", "1"],
        ["/usr/bin/gunicorn", "cinefin.wsgi:application"],
        ["manage.py", "runserver"],
        ["manage.py", "migrate"],
    ],
)
def test_single_worker_configurations_boot(monkeypatch, argv):
    _run_guard(monkeypatch, argv)


@pytest.mark.parametrize(
    ("argv", "cmd_args"),
    [
        (["/usr/bin/gunicorn", "cinefin.wsgi:application", "--workers", "4"], ""),
        (["/usr/bin/gunicorn", "cinefin.wsgi:application", "--workers=2"], ""),
        (["/usr/bin/gunicorn", "cinefin.wsgi:application", "-w", "8"], ""),
        (["/usr/bin/gunicorn", "cinefin.wsgi:application"], "--workers 4"),
    ],
)
def test_multi_worker_configurations_refuse_to_boot(monkeypatch, argv, cmd_args):
    with pytest.raises(ImproperlyConfigured, match="exactly one gunicorn worker"):
        _run_guard(monkeypatch, argv, cmd_args)
