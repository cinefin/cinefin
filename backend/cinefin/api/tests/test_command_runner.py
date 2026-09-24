import time

import pytest
import requests

from cinefin.api.models import Command
from cinefin.api.services import command_runner

from .factories import CommandFactory

pytestmark = pytest.mark.django_db


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 400


class TestProviders:
    def test_rest_success(self, monkeypatch):
        captured = {}

        def fake_request(method, url, **kwargs):
            captured.update(method=method, url=url, **kwargs)
            return FakeResponse(200, '{"result": "fine"}')

        monkeypatch.setattr(requests, "request", fake_request)
        command = CommandFactory(
            provider="rest",
            config={
                "method": "POST",
                "url": "http://ha.local/api/webhook/x",
                "headers": {"X-K": "v"},
                "body": {"a": 1},
            },
        )
        result = command_runner.execute(command, trigger="remote", wait=True)

        assert result.ok is True
        assert result.detail == "HTTP 200"
        assert "fine" in result.output
        assert captured["method"] == "POST"
        assert captured["json"] == {"a": 1}

    def test_rest_failure_reports_status(self, monkeypatch):
        monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse(500, "boom"))
        command = CommandFactory(provider="rest", config={"url": "http://x.invalid/"})
        result = command_runner.execute(command, trigger="test", wait=True)
        assert result.ok is False
        assert result.detail == "HTTP 500"

    def test_rest_transport_error_is_caught(self, monkeypatch):
        def boom(*args, **kwargs):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests, "request", boom)
        command = CommandFactory(provider="rest", config={"url": "http://nope.invalid/"})
        result = command_runner.execute(command, trigger="test", wait=True)
        assert result.ok is False
        assert result.detail == "ConnectionError"

    def test_unknown_provider(self):
        command = Command(name="odd", provider="carrier-pigeon", config={})
        result = command_runner.execute(command, trigger="test", wait=True)
        assert result.ok is False
        assert "unknown provider" in result.detail

    def test_output_is_capped(self, monkeypatch):
        monkeypatch.setattr(
            requests,
            "request",
            lambda *a, **k: FakeResponse(200, "x" * (command_runner.OUTPUT_CAP + 500)),
        )
        command = CommandFactory(provider="rest", config={"url": "http://x.invalid/"})
        result = command_runner.execute(command, trigger="test", wait=True)
        assert "truncated" in result.output
        assert len(result.output) < command_runner.OUTPUT_CAP + 200


class TestSequential:
    @pytest.mark.django_db(transaction=True)
    def test_sequential_runs_in_order(self, monkeypatch):
        fired: list[str] = []

        def fake_request(method, url, **kwargs):
            fired.append(url)
            return FakeResponse(200, "")

        monkeypatch.setattr(requests, "request", fake_request)
        first = CommandFactory(name="First", config={"url": "http://x.invalid/first"})
        second = CommandFactory(name="Second", config={"url": "http://x.invalid/second"})

        command_runner.execute_many_sequential([first, second], trigger="preshow")

        deadline = time.time() + 10
        while len(fired) < 2 and time.time() < deadline:
            time.sleep(0.05)

        assert fired == ["http://x.invalid/first", "http://x.invalid/second"]


class TestEndpoints:
    def test_execute_endpoint_returns_result(self, client, monkeypatch):
        monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse(200, "hi"))
        command = CommandFactory(config={"url": "http://x.invalid/"})
        response = client.post(f"/api/v2/commands/{command.id}/execute")
        assert response.status_code == 200
        assert response.json()["data"]["result"] == {"ok": True, "detail": "HTTP 200", "output": "hi"}

    def test_create_validates_provider_config(self, client):
        response = client.post(
            "/api/v2/commands/create",
            data={"name": "Broken", "provider": "rest", "config": {}},
            content_type="application/json",
        )
        assert response.status_code == 400
