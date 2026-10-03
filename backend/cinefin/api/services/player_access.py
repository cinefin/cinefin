"""A player's access to Cinefin's API, for players that browse and start programmes themselves.

A player that lists ``browse`` in its ``features`` (an Android TV player) is
sent Cinefin's address, an API key of its own and its host id (``PUT
/cinefin``), so it can list programmes and cue them on itself. Only the key's
hash is kept, so a key is sent once: a new one is minted when the player is
paired and whenever Cinefin's address changes, and the old one is deleted once
the new one is delivered. A key revoked on the Security page stays revoked:
the host keeps ``access_url``, so nothing is sent again until it is paired again.
"""

import logging
import threading

from django.db import close_old_connections

from cinefin.api.exceptions import APIException
from cinefin.api.models import APIKey, PlayoutHost
from cinefin.api.utils.urls import cinefin_base_url

logger = logging.getLogger(__name__)

FEATURE = "browse"

# One send at a time, so two pushes never mint two keys for one host.
_lock = threading.Lock()


def features(answer: dict) -> list[str]:
    """The agent's ``features`` (strings only), from its /pair or /health answer."""
    listed = answer.get("features")
    return [f for f in listed if isinstance(f, str)] if isinstance(listed, list) else []


def wants_access(host: PlayoutHost) -> bool:
    return (
        host.kind == PlayoutHost.KIND_AGENT and bool(host.token) and host.enabled and FEATURE in (host.features or [])
    )


def needs_send(host: PlayoutHost) -> bool:
    """Never sent (or not delivered yet), or sent to an address Cinefin has since left."""
    if not wants_access(host):
        return False
    if not host.access_url:
        return True
    return host.api_key_id is not None and host.access_url != cinefin_base_url()


def _send(host: PlayoutHost) -> bool:
    from cinefin.api.services.playout_agent_service import playout_agent_service

    base = cinefin_base_url()
    key, raw = APIKey.create(f"Player: {host.name}")
    try:
        playout_agent_service.put_cinefin(host, {"base_url": base, "api_key": raw, "host_id": host.id})
    except APIException as e:
        key.delete()
        logger.info("Cinefin's address and key not sent to %s: %s", host.name, e.message)
        return False
    old = host.api_key_id
    host.api_key = key
    host.access_url = base
    host.save(update_fields=["api_key", "access_url", "updated_at"])
    if old is not None:
        APIKey.objects.filter(pk=old).delete()
    logger.info("Sent %s Cinefin's address and a key", host.name)
    return True


def push_now(host_ids: list[int] | None = None) -> None:
    hosts = PlayoutHost.objects.filter(kind=PlayoutHost.KIND_AGENT, enabled=True).exclude(token="")
    if host_ids is not None:
        hosts = hosts.filter(id__in=host_ids)
    for host in hosts:
        with _lock:
            host.refresh_from_db()
            if needs_send(host):
                _send(host)


def push(host_ids: list[int] | None = None) -> None:
    """Send players that need it Cinefin's address and a key, in the background.
    Called on pairing, refresh, standby and a change of the streaming URL."""

    def run():
        try:
            push_now(host_ids)
        except Exception:  # noqa: BLE001
            logger.warning("Player access push failed", exc_info=True)
        finally:
            close_old_connections()

    threading.Thread(target=run, name="player-access-push", daemon=True).start()


def push_if_needed(host: PlayoutHost) -> None:
    """``push`` for one host, only when it needs a send (cheap to call often)."""
    if needs_send(host):
        push([host.id])


def forget(host: PlayoutHost) -> None:
    """Delete the host's key and forget what was sent: on pairing again and on removal."""
    if host.api_key_id is not None:
        APIKey.objects.filter(pk=host.api_key_id).delete()
    host.api_key = None
    host.access_url = ""
    if host.pk is not None:
        host.save(update_fields=["api_key", "access_url", "updated_at"])
