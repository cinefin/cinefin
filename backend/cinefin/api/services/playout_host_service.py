"""Service helpers for PlayoutHost: poll a host's agent and record liveness/version facts."""

import logging

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

STATUS_TIMEOUT = 5


class PlayoutHostService:
    @staticmethod
    def _headers(host) -> dict:
        token = host.token or ""
        return {"Authorization": f"Bearer {token}"} if token else {}

    @classmethod
    def _get(cls, host, path: str) -> dict | None:
        base = (host.base_url or "").rstrip("/")
        url = f"{base}{path}"
        try:
            response = requests.get(url, headers=cls._headers(host), timeout=STATUS_TIMEOUT)
        except requests.RequestException as e:
            logger.warning("PlayoutHost %s unreachable at %s: %s", host.name, url, e)
            return None
        if not response.ok:
            logger.warning("PlayoutHost %s agent error (%s) at %s", host.name, response.status_code, url)
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @classmethod
    def refresh(cls, host) -> bool:
        """Poll the host's agent, update liveness/version facts. True if reachable. Never raises."""
        health = cls._get(host, "/health")
        status = cls._get(host, "/status")
        payload = health or status
        if payload is None:
            return False

        host.last_seen_at = timezone.now()
        # Lenient about field location so a slightly different agent shape still records what it can.
        agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else payload
        version = payload.get("version") or agent.get("version")
        os_name = payload.get("os") or agent.get("os")
        arch = payload.get("arch") or agent.get("arch")
        if version:
            host.agent_version = version
        if os_name:
            host.os = os_name
        if arch:
            host.arch = arch
        host.save()
        return True


playout_host_service = PlayoutHostService()
