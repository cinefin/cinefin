import time

import pytest
import requests

from cinefin.api.services import command_runner

from .factories import CommandFactory

pytestmark = pytest.mark.django_db


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 400


def run(config):
    return command_runner.execute(CommandFactory(provider="rest", config=config), trigger="test", wait=True)


def test_rest_success(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return FakeResponse(200, '{"result": "fine"}')

    monkeypatch.setattr(requests, "request", fake_request)
    result = run({"method": "POST", "url": "http://ha.local/x", "headers": {"X-K": "v"}, "body": {"a": 1}})
    assert (result.ok, result.detail) == (True, "HTTP 200") and "fine" in result.output
    assert (captured["method"], captured["json"]) == ("POST", {"a": 1})


def _refused(*args, **kwargs):
    raise requests.ConnectionError("refused")


@pytest.mark.parametrize(
    ("request_fn", "detail"),
    [(lambda *a, **k: FakeResponse(500, "boom"), "HTTP 500"), (_refused, "ConnectionError")],
)
def test_rest_failures_are_results(monkeypatch, request_fn, detail):
    monkeypatch.setattr(requests, "request", request_fn)
    result = run({"url": "http://x.invalid/"})
    assert (result.ok, result.detail) == (False, detail)


@pytest.mark.django_db(transaction=True)
def test_sequential_runs_in_order(monkeypatch):
    fired = []
    monkeypatch.setattr(requests, "request", lambda method, url, **kw: fired.append(url) or FakeResponse())
    first = CommandFactory(config={"url": "http://x.invalid/first"})
    second = CommandFactory(config={"url": "http://x.invalid/second"})
    command_runner.execute_many_sequential([first, second], trigger="preshow")
    deadline = time.time() + 10
    while len(fired) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert fired == ["http://x.invalid/first", "http://x.invalid/second"]


def test_execute_endpoint_returns_result(client, monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse(200, "hi"))
    response = client.post(f"/api/v2/commands/{CommandFactory().id}/execute")
    assert response.json()["data"]["result"] == {"ok": True, "detail": "HTTP 200", "output": "hi"}
