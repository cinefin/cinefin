"""HTTP client for the cinefin-playout agent (mpv process + host launch config).

Playback control does NOT go through here — it rides the WS control channel via
``mpv_service`` / ``MPVController``. Graphics/audio are set from here and kept by the
agent (in its state file), so the box boots with Cinefin offline.

The bearer token comes from pairing: the player shows a short code on its screen,
and ``pair()`` exchanges it for the token (``POST /pair``)."""

import logging

import requests

from cinefin.api.exceptions import ConflictError, UnprocessableEntityError, ValidationError
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
                "The player no longer accepts this Cinefin — remove it and pair it again",
                error_code="AGENT_AUTH_FAILED",
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

    @staticmethod
    def pair(base_url: str, code: str) -> dict:
        """Exchange the code shown on the player's screen for its bearer token.

        Returns the agent's answer: ``token``, ``id``, ``name``, ``agent_version``,
        ``os``, ``arch``. Raises a ValidationError the user can act on for a wrong
        or rate-limited code, a ConflictError when the player is paired elsewhere.
        """
        base = base_url.strip().rstrip("/")
        try:
            response = requests.post(f"{base}/pair", json={"code": code}, timeout=STATUS_TIMEOUT)
        except requests.RequestException as e:
            raise UnprocessableEntityError(f"No player answered at {base}: {e}", error_code="AGENT_UNREACHABLE") from e
        if response.status_code == 403:
            raise ValidationError(
                "That code is not right. Check the code on the player's screen; it changes after each try.",
                error_code="PAIR_WRONG_CODE",
                details={"field": "code"},
            )
        if response.status_code == 429:
            raise ValidationError(
                "Too many tries. Wait a minute, then enter the code on the player's screen.",
                error_code="PAIR_RATE_LIMITED",
                details={"field": "code"},
            )
        if response.status_code == 409:
            raise ConflictError(
                "This player is already paired with a Cinefin. On the player, choose Forget Cinefin in the "
                "tray or run `cinefin-playout reset`, then try again.",
                error_code="PAIR_ALREADY_PAIRED",
            )
        if response.status_code == 404:
            raise UnprocessableEntityError(
                "That player's agent is too old to pair. Update cinefin-playout.", error_code="AGENT_OUTDATED"
            )
        if not response.ok:
            raise UnprocessableEntityError(
                f"Pairing failed ({response.status_code}): {response.text[:200]}", error_code="AGENT_ERROR"
            )
        try:
            answer = response.json()
        except ValueError:
            answer = {}
        if not answer.get("token"):
            raise UnprocessableEntityError("The player did not return a token", error_code="AGENT_ERROR")
        return answer

    @classmethod
    def unpair(cls, host) -> bool:
        """Tell a host's agent to forget this Cinefin (it then shows a pairing code). Best effort."""
        if host is None or host.kind != PlayoutHost.KIND_AGENT or not host.token:
            return False
        try:
            base, token = cls.host_target(host)
            cls._request("POST", "/unpair", timeout=STATUS_TIMEOUT, base_override=base, token_override=token)
            return True
        except UnprocessableEntityError as e:
            logger.info("Unpairing %s skipped: %s", host.name, e.message)
            return False

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
