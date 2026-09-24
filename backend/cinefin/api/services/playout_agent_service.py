"""HTTP client for the cinefin-playout agent (mpv process + host launch config).

Playback control does NOT go through here — it rides the WS control channel via
``mpv_service`` / ``MPVController``. Graphics/audio are host-owned (persisted to the
agent's config.toml, the source of truth so the box boots with Cinefin offline)."""

import logging

import requests

from cinefin.api.exceptions import UnprocessableEntityError
from cinefin.api.models import PlayoutHost, Settings

logger = logging.getLogger(__name__)

STATUS_TIMEOUT = 5
# start/restart block until mpv's IPC socket is up (the agent waits internally)
ACTION_TIMEOUT = 25


class PlayoutAgentService:
    """Authenticated HTTP proxy to the active playout host's agent."""

    @staticmethod
    def resolve() -> tuple[str, str]:
        """The active agent host's ``(base_url, token)``; ``""`` when no agent host is active."""
        host = PlayoutHost.get_active()
        if host is not None and host.kind == PlayoutHost.KIND_AGENT and (host.base_url or "").strip():
            return host.base_url.strip().rstrip("/"), (host.token or "")
        return "", ""

    @classmethod
    def is_configured(cls) -> bool:
        base, _ = cls.resolve()
        return bool(base)

    @classmethod
    def _request(
        cls, method, path, json_body=None, timeout=ACTION_TIMEOUT, base_override=None, token_override=None
    ) -> dict:
        if base_override is not None:
            base, token = base_override.rstrip("/"), (token_override or "")
        else:
            base, token = cls.resolve()
        if not base:
            raise UnprocessableEntityError(
                "No playout host is configured — add one on the Playout settings page",
                error_code="AGENT_NOT_CONFIGURED",
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = requests.request(method, f"{base}{path}", json=json_body, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            raise UnprocessableEntityError(
                f"Playout agent unreachable at {base}: {e}", error_code="AGENT_UNREACHABLE"
            ) from e
        if response.status_code == 401:
            raise UnprocessableEntityError(
                "Playout agent rejected the token — check the host's token", error_code="AGENT_AUTH_FAILED"
            )
        if response.status_code == 400:
            # Surface the agent's validation error verbatim — the most useful thing to read.
            try:
                detail = (response.json() or {}).get("error") or response.text
            except ValueError:
                detail = response.text
            raise UnprocessableEntityError(str(detail)[:300], error_code="AGENT_REJECTED")
        if not response.ok:
            raise UnprocessableEntityError(
                f"Playout agent error ({response.status_code}): {response.text[:200]}", error_code="AGENT_ERROR"
            )
        try:
            return response.json()
        except ValueError:
            return {}

    @classmethod
    def get_status(cls) -> dict:
        return cls._request("GET", "/status", timeout=STATUS_TIMEOUT)

    @staticmethod
    def host_target(host) -> tuple[str, str]:
        """``(base_url, token)`` for one host row (config calls address a host directly)."""
        if host is not None and host.kind == PlayoutHost.KIND_AGENT and (host.base_url or "").strip():
            return host.base_url.strip().rstrip("/"), (host.token or "")
        raise UnprocessableEntityError(
            "That host has no agent to configure — only agent hosts carry a launch config",
            error_code="AGENT_NOT_CONFIGURED",
        )

    @classmethod
    def get_host_config(cls, host) -> dict:
        """The named host's launch config: autostart + graphics + audio."""
        base, token = cls.host_target(host)
        return cls._request("GET", "/hostconfig", timeout=STATUS_TIMEOUT, base_override=base, token_override=token)

    @classmethod
    def put_host_config(cls, host, config: dict) -> dict:
        """Replace the named host's launch config (agent validates + persists). Returns restart_required."""
        base, token = cls.host_target(host)
        return cls._request(
            "PUT", "/hostconfig", json_body=config, timeout=ACTION_TIMEOUT, base_override=base, token_override=token
        )

    @classmethod
    def get_hardware(cls, host) -> dict:
        """The host's real device lists. Enumerated on demand, so slow — hence the longer timeout."""
        base, token = cls.host_target(host)
        return cls._request("GET", "/hardware", timeout=ACTION_TIMEOUT, base_override=base, token_override=token)

    @classmethod
    def get_hostconfig(cls) -> dict:
        return cls._request("GET", "/hostconfig", timeout=STATUS_TIMEOUT)

    @classmethod
    def put_idle_media(cls, url: str) -> dict:
        """Set only ``graphics.idle_media`` on the agent, leaving every other setting untouched."""
        return cls._request("PUT", "/hostconfig/idle-media", json_body={"idle_media": url}, timeout=STATUS_TIMEOUT)

    @staticmethod
    def ident_idle_media_url() -> str:
        """Streaming URL of the ident the agent idles on (user media item, else System Ident)."""
        from cinefin.api.models import Bumper
        from cinefin.api.utils.assets import system_ident_stream_url

        ident_id = Settings.get("cinema.default_ident_id")
        if ident_id:
            try:
                bumper = Bumper.objects.get(id=ident_id)
            except Bumper.DoesNotExist:
                pass
            else:
                url = (bumper.get_stream_url() or {}).get("stream_url", "")
                if url:
                    return url
        return system_ident_stream_url()

    @classmethod
    def resync_idle_media(cls) -> None:
        """Best-effort push of the current ident. A disconnected/absent host is not an error."""
        if not cls.is_configured():
            return
        try:
            cls.put_idle_media(cls.ident_idle_media_url())
        except UnprocessableEntityError as e:
            logger.info("Idle-media resync skipped (agent unavailable): %s", e.message)

    @classmethod
    def start_mpv(cls) -> dict:
        return cls._request("POST", "/mpv/start")

    @classmethod
    def stop_mpv(cls) -> dict:
        return cls._request("POST", "/mpv/stop")

    @classmethod
    def restart_mpv(cls) -> dict:
        return cls._request("POST", "/mpv/restart")

    @classmethod
    def ensure_mpv_running(cls) -> bool:
        """Best-effort auto-start before playout. True if mpv is (now) running on the active host."""
        if not cls.is_configured():
            return False
        try:
            status = cls.get_status()
            mpv = status.get("mpv") or {}
            if mpv.get("running") or mpv.get("socket_responding"):
                return True
            cls.start_mpv()
            logger.info("Playout agent asked to start MPV before playout")
            return True
        except UnprocessableEntityError as e:
            logger.warning("MPV auto-start via playout agent failed: %s", e.message)
        return False


playout_agent_service = PlayoutAgentService()
