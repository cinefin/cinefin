"""Find cinefin-playout agents on the local network.

Each agent announces itself over mDNS as ``_cinefin-playout._tcp`` with TXT
records ``id``, ``name``, ``version`` and ``paired``. A browse lasts a couple of
seconds; every answer is then confirmed with the agent's own ``/health`` (so a
stale mDNS cache entry, or an address that does not route from here, is dropped)
and matched against the ``PlayoutHost`` rows by ``agent_id``.

mDNS does not cross a Docker bridge network, so a containerised Cinefin finds
nothing here; the Playout page falls back to adding a player by address.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests
from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf

from cinefin.api.models import PlayoutHost

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_cinefin-playout._tcp.local."
BROWSE_SECONDS = 2.0
HEALTH_TIMEOUT = 1.5


@dataclass
class Announcement:
    """One raw mDNS answer: TXT properties plus the addresses and port."""

    properties: dict[str, str]
    addresses: list[str]
    port: int


@dataclass
class DiscoveredPlayer:
    id: str
    name: str
    base_url: str
    version: str
    paired: bool
    host_id: int | None  # the PlayoutHost this player already is, if any


class _Names(ServiceListener):
    def __init__(self):
        self.names: set[str] = set()

    def add_service(self, zc, type_, name):
        self.names.add(name)

    def update_service(self, zc, type_, name):
        self.names.add(name)

    def remove_service(self, zc, type_, name):
        self.names.discard(name)


def browse(seconds: float = BROWSE_SECONDS) -> list[Announcement]:
    """Collect the mDNS announcements seen within ``seconds``."""
    zc = Zeroconf()
    try:
        listener = _Names()
        ServiceBrowser(zc, SERVICE_TYPE, listener)
        time.sleep(seconds)
        found = []
        for name in sorted(listener.names):
            info = zc.get_service_info(SERVICE_TYPE, name, timeout=1500)
            if info is None or not info.port:
                continue
            props = {
                (k or b"").decode(errors="replace"): (v or b"").decode(errors="replace")
                for k, v in (info.properties or {}).items()
            }
            # IPv4 first: it is what a home LAN routes, and it reads well in a URL.
            addrs = info.parsed_addresses(IPVersion.V4Only) + info.parsed_addresses(IPVersion.V6Only)
            found.append(Announcement(properties=props, addresses=addrs, port=info.port))
        return found
    finally:
        zc.close()


def base_url_for(address: str, port: int) -> str:
    host = f"[{address}]" if ":" in address else address
    return f"http://{host}:{port}"


def _confirm(ann: Announcement) -> tuple[str, dict] | None:
    """The first address whose /health answers with the announced id."""
    want = ann.properties.get("id", "")
    for addr in ann.addresses:
        url = base_url_for(addr, ann.port)
        try:
            health = requests.get(f"{url}/health", timeout=HEALTH_TIMEOUT).json()
        except (requests.RequestException, ValueError):
            continue
        if want and health.get("id") == want:
            return url, health
    return None


def resolve(announcements: list[Announcement]) -> list[DiscoveredPlayer]:
    """Confirm announcements over HTTP, de-duplicate by id and match known hosts."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        confirmed = list(pool.map(_confirm, announcements))

    by_id: dict[str, DiscoveredPlayer] = {}
    for ann, hit in zip(announcements, confirmed, strict=True):
        if hit is None:
            continue
        url, health = hit
        agent_id = health["id"]
        if agent_id in by_id:
            continue
        host = PlayoutHost.objects.filter(kind=PlayoutHost.KIND_AGENT, agent_id=agent_id).first()
        by_id[agent_id] = DiscoveredPlayer(
            id=agent_id,
            name=health.get("name") or ann.properties.get("name") or url,
            base_url=url,
            version=health.get("version") or ann.properties.get("version", ""),
            paired=bool(health.get("paired")),
            host_id=host.id if host else None,
        )
    return sorted(by_id.values(), key=lambda p: p.name.lower())


def discover(seconds: float = BROWSE_SECONDS) -> list[DiscoveredPlayer]:
    """Players on the local network right now. Never raises: mDNS trouble yields []."""
    try:
        announcements = browse(seconds)
    except Exception:  # noqa: BLE001 — no multicast (container, no network) is not an error
        logger.info("Playout discovery unavailable", exc_info=True)
        return []
    return resolve(announcements)
