"""Find Home Assistant instances on the local network: mDNS first, then well-known hostnames."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

MDNS_SERVICE_TYPE = "_home-assistant._tcp.local."
MDNS_BROWSE_SECONDS = 2.5
FALLBACK_HOSTS = ("homeassistant.local", "homeassistant")


def _mdns_discover(browse_seconds: float = MDNS_BROWSE_SECONDS) -> list[dict]:
    from zeroconf import ServiceBrowser, Zeroconf

    found: dict[str, dict] = {}

    class _Listener:
        def add_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name, timeout=int(browse_seconds * 1000))
            if info is None:
                return
            props = {}
            for key, value in (info.properties or {}).items():
                if isinstance(key, bytes) and isinstance(value, bytes):
                    props[key.decode(errors="replace")] = value.decode(errors="replace")
            addresses = info.parsed_addresses()
            url = props.get("internal_url") or props.get("base_url")
            if not url and addresses:
                url = f"http://{addresses[0]}:{info.port}"
            if url:
                found[name] = {
                    "url": url.rstrip("/"),
                    "name": props.get("location_name") or name.split(".")[0],
                    "version": props.get("version"),
                }

        def update_service(self, zc, service_type, name):
            pass

        def remove_service(self, zc, service_type, name):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, MDNS_SERVICE_TYPE, _Listener())
        time.sleep(browse_seconds)
    finally:
        zc.close()
    return list(found.values())


def _probe_fallback() -> list[dict]:
    candidates = []
    for host in FALLBACK_HOSTS:
        url = f"http://{host}:8123"
        try:
            response = requests.get(f"{url}/api/", timeout=2)
        except requests.RequestException:
            continue
        if response.status_code in (200, 401, 403):
            candidates.append({"url": url, "name": host, "version": None})
    return candidates


def discover_instances() -> list[dict]:
    """[{"url", "name", "version"}] — empty when nothing answers."""
    try:
        candidates = _mdns_discover()
    except Exception:  # noqa: BLE001 - mDNS can fail in containers; fall back to hostnames
        logger.exception("mDNS discovery failed; falling back to hostname probes")
        candidates = []
    return candidates or _probe_fallback()
