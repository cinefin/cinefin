"""HTTP client for the cinefin-playout agent (mpv process + host launch config).

Playback control does NOT go through here — it rides the WS control channel via
``mpv_service`` / ``MPVController``. Graphics/audio are set from here and kept by the
agent (in its state file), so the box boots with Cinefin offline.

The bearer token comes from pairing: the player shows a short code on its screen,
and ``pair()`` exchanges it for the token (``POST /pair``)."""

import logging

import requests

from cinefin.api.exceptions import ConflictError, UnprocessableEntityError, ValidationError
from cinefin.api.models import PlayoutHost

logger = logging.getLogger(__name__)

STATUS_TIMEOUT = 5
# start/restart block until mpv's IPC socket is up (the agent waits internally). A restart
# can take the agent up to 28 s when mpv is slow to quit, so leave room over that.
ACTION_TIMEOUT = 35

# The agent protocol this Cinefin speaks: 2 = pairing by code, the player owns standby.
# The player serves a range (min_protocol..protocol, from /health and /pair) and refuses a
# Cinefin outside it with 426; Cinefin sends PROTOCOL in PROTOCOL_HEADER on every request.
# Raise it when Cinefin starts to rely on something new in the player (which raises its own).
PROTOCOL = 2
PROTOCOL_HEADER = "Cinefin-Protocol"
OUTDATED_MESSAGE = "This player needs updating to the latest cinefin-playout release"
CINEFIN_OUTDATED_MESSAGE = "This player needs a newer Cinefin. Update Cinefin to the latest release"

COMPATIBLE = "ok"
UPDATE_PLAYER = "update_player"
UPDATE_CINEFIN = "update_cinefin"


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def compatibility(answer: dict) -> str:
    """Whether an agent's /pair or /health answer serves PROTOCOL: ``COMPATIBLE``, or which side to update."""
    protocol = _int(answer.get("protocol"))
    if protocol is None or protocol < PROTOCOL:
        return UPDATE_PLAYER
    # A player from before the range reports no min_protocol: it serves anything up to protocol.
    if (_int(answer.get("min_protocol")) or 0) > PROTOCOL:
        return UPDATE_CINEFIN
    return COMPATIBLE


def headers(token: str = "") -> dict:
    """The headers for every request to an agent: the protocol, and the bearer token once paired."""
    out = {PROTOCOL_HEADER: str(PROTOCOL)}
    if token:
        out["Authorization"] = f"Bearer {token}"
    return out


def _agent_error(response) -> str:
    """The agent's own ``{"error": ...}`` (or an action's ``{"message": ...}``), else its body."""
    try:
        body = response.json() or {}
        detail = (
            (body.get("error") or body.get("message") or response.text) if isinstance(body, dict) else response.text
        )
    except ValueError:
        detail = response.text
    return str(detail)[:300]


def _protocol_refusal(response) -> UnprocessableEntityError:
    """The error for an agent's 426: which side to update, in the agent's own words."""
    try:
        body = response.json() or {}
    except ValueError:
        body = {}
    if (_int(body.get("min_protocol")) or 0) > PROTOCOL:
        return UnprocessableEntityError(
            _agent_error(response) or CINEFIN_OUTDATED_MESSAGE, error_code="AGENT_NEEDS_NEWER_CINEFIN"
        )
    return UnprocessableEntityError(OUTDATED_MESSAGE, error_code="AGENT_OUTDATED")


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
    def _request(cls, method, path, json_body=None, timeout=ACTION_TIMEOUT, host=None) -> dict:
        """Call the agent of ``host``, else of the active host."""
        base, token = cls.host_target(host) if host is not None else cls.resolve()
        if not base:
            raise UnprocessableEntityError(
                "No playout host is configured — add one on the Playout settings page",
                error_code="AGENT_NOT_CONFIGURED",
            )
        try:
            response = requests.request(
                method, f"{base}{path}", json=json_body, headers=headers(token), timeout=timeout
            )
        except requests.RequestException as e:
            raise UnprocessableEntityError(
                f"Playout agent unreachable at {base}: {e}", error_code="AGENT_UNREACHABLE"
            ) from e
        if response.status_code == 426:
            raise _protocol_refusal(response)
        if response.status_code == 401:
            raise UnprocessableEntityError(
                "The player no longer accepts this Cinefin — remove it and pair it again",
                error_code="AGENT_AUTH_FAILED",
            )
        if response.status_code == 409:
            # The agent refused for now (a test sound already playing, not on standby): say why.
            detail = _agent_error(response)
            raise ConflictError(detail[:1].upper() + detail[1:], error_code="AGENT_BUSY")
        if response.status_code == 400:
            # Surface the agent's validation error verbatim — the most useful thing to read.
            raise UnprocessableEntityError(_agent_error(response), error_code="AGENT_REJECTED")
        if not response.ok:
            raise UnprocessableEntityError(
                f"Playout agent error ({response.status_code}): {_agent_error(response)}", error_code="AGENT_ERROR"
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
            response = requests.post(f"{base}/pair", json={"code": code}, headers=headers(), timeout=STATUS_TIMEOUT)
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
        if response.status_code == 426:
            raise _protocol_refusal(response)
        if response.status_code == 404:
            raise UnprocessableEntityError(OUTDATED_MESSAGE, error_code="AGENT_OUTDATED")
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
        verdict = compatibility(answer)
        if verdict == UPDATE_PLAYER:
            raise UnprocessableEntityError(OUTDATED_MESSAGE, error_code="AGENT_OUTDATED")
        if verdict == UPDATE_CINEFIN:
            raise UnprocessableEntityError(CINEFIN_OUTDATED_MESSAGE, error_code="AGENT_NEEDS_NEWER_CINEFIN")
        return answer

    @classmethod
    def unpair(cls, host) -> bool:
        """Tell a host's agent to forget this Cinefin (it then shows a pairing code). Best effort."""
        if host is None or host.kind != PlayoutHost.KIND_AGENT or not host.token:
            return False
        try:
            cls._request("POST", "/unpair", timeout=STATUS_TIMEOUT, host=host)
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
        return cls._request("GET", "/hostconfig", timeout=STATUS_TIMEOUT, host=host)

    @classmethod
    def put_host_config(cls, host, config: dict) -> dict:
        """Replace the named host's launch config (agent validates + persists). Returns restart_required."""
        return cls._request("PUT", "/hostconfig", json_body=config, host=host)

    @classmethod
    def get_hardware(cls, host) -> dict:
        """The host's real device lists. Enumerated on demand, so slow — hence the longer timeout."""
        return cls._request("GET", "/hardware", host=host)

    @classmethod
    def put_standby(cls, host, spec: dict) -> dict:
        """Send the host its standby spec (``services/standby.py``). Returns its standby status."""
        return cls._request("PUT", "/standby", json_body=spec, timeout=STATUS_TIMEOUT, host=host)

    @classmethod
    def put_cinefin(cls, host, access: dict) -> dict:
        """Send a browsing player Cinefin's address, its API key and host id (``services/player_access.py``)."""
        return cls._request("PUT", "/cinefin", json_body=access, timeout=STATUS_TIMEOUT, host=host)

    @classmethod
    def enter_standby(cls, host) -> dict:
        """Put the host's player on standby now. Returns its standby status."""
        return cls._request("POST", "/standby", timeout=STATUS_TIMEOUT, host=host)

    @classmethod
    def test_card(cls, host, on: bool) -> dict:
        """Show or hide the host's test card. Returns ``on``, ``off_in_s``."""
        return cls._request("POST", "/testcard", json_body={"on": on}, timeout=STATUS_TIMEOUT, host=host)

    @classmethod
    def test_sound(cls, host) -> dict:
        """Play the host's left-then-right test tone (ConflictError while one plays or off standby)."""
        return cls._request("POST", "/testsound", timeout=STATUS_TIMEOUT, host=host)

    @classmethod
    def restart_host(cls, host) -> dict:
        """Restart the named host's mpv, so a changed launch config applies."""
        return cls._request("POST", "/mpv/restart", host=host)

    @classmethod
    def host_status(cls, host) -> dict:
        return cls._request("GET", "/status", timeout=STATUS_TIMEOUT, host=host)

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
