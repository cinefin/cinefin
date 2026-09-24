"""Home Assistant: call any Home Assistant service (lights, scenes, blinds, media players)."""

import requests

from cinefin.plugins import RUN_TIMEOUT, CommandProvider, Field, register

from .discovery import discover_instances

SUGGESTIONS_TIMEOUT = 5
TEST_TIMEOUT = 5


def _connection(settings):
    return (settings.get("url") or "").strip().rstrip("/"), (settings.get("token") or "").strip()


def _get(base_url, token, path, timeout):
    response = requests.get(f"{base_url}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    response.raise_for_status()
    return response.json()


@register
class HomeAssistantProvider(CommandProvider):
    id = "homeassistant"
    label = "Home Assistant"
    icon = "house"
    description = "Call a Home Assistant service"
    fields = [
        Field("domain", required=True, placeholder="scene"),
        Field("service", required=True, placeholder="turn_on", scoped_by="domain"),
        Field("entity_id", "Entity ID", placeholder="scene.cinema_dim", scoped_by="domain"),
        Field("data", "Service data (JSON)", type="json", placeholder='{"brightness": 40}'),
    ]
    settings = [
        Field(
            "url",
            "Home Assistant URL",
            required=True,
            placeholder="http://homeassistant.local:8123",
            help="Base URL of your Home Assistant, reachable from this server - or let Discover find it.",
        ),
        Field(
            "token",
            "Long-lived access token",
            type="secret",
            required=True,
            placeholder="eyJhbGciOi…",
            help="Create one in Home Assistant under your profile → Security → Long-lived access tokens.",
        ),
    ]

    def run(self, config, settings):
        base_url, token = _connection(settings)
        if not base_url or not token:
            return False, "Home Assistant is not configured (Settings → Plugins)", ""
        domain = (config.get("domain") or "").strip()
        service = (config.get("service") or "").strip()
        if not domain or not service:
            return False, "no Home Assistant domain/service configured", ""

        payload = dict(config.get("data") or {})
        if config.get("entity_id"):
            payload["entity_id"] = config["entity_id"]
        try:
            response = requests.post(
                f"{base_url}/api/services/{domain}/{service}",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
                timeout=RUN_TIMEOUT,
            )
            return response.ok, f"HTTP {response.status_code}", response.text
        except requests.RequestException as exc:
            return False, exc.__class__.__name__, str(exc)

    def summary(self, config):
        # Older commands may carry only an entity_id — never show "?.?".
        domain, service, entity = config.get("domain"), config.get("service"), config.get("entity_id")
        action = f"{domain}.{service}" if domain and service else service or ""
        if action and entity:
            return f"{action} → {entity}"
        return action or entity or ""

    def suggestions(self, settings):
        base_url, token = _connection(settings)
        if not base_url or not token:
            raise ValueError("Home Assistant is not configured — set it up in Settings → Plugins")
        try:
            services = _get(base_url, token, "/api/services", SUGGESTIONS_TIMEOUT)
            states = _get(base_url, token, "/api/states", SUGGESTIONS_TIMEOUT)
        except requests.RequestException as exc:
            raise ValueError(f"Home Assistant is not reachable ({exc.__class__.__name__})") from exc

        return {
            "domain": [{"value": d} for d in sorted(e["domain"] for e in services if e.get("domain"))],
            "service": [
                {"value": name, "scope": entry["domain"]}
                for entry in services
                if entry.get("domain")
                for name in sorted(entry.get("services") or {})
            ],
            "entity_id": sorted(
                (
                    {
                        "value": state["entity_id"],
                        "label": (state.get("attributes") or {}).get("friendly_name") or state["entity_id"],
                        "scope": state["entity_id"].split(".", 1)[0],
                    }
                    for state in states
                    if state.get("entity_id")
                ),
                key=lambda s: s["value"],
            ),
        }

    def test_settings(self, settings):
        base_url, token = _connection(settings)
        if not base_url or not token:
            return False, "Enter a URL and access token first."
        try:
            config = _get(base_url, token, "/api/config", TEST_TIMEOUT)
        except requests.HTTPError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                return False, "Unauthorized — check the access token"
            return False, f"HTTP {status} from {base_url}"
        except requests.RequestException as exc:
            return False, f"{exc.__class__.__name__}: could not reach {base_url}"
        location = config.get("location_name")
        return (
            True,
            f"Connected to {location or base_url} (Home Assistant {config.get('version') or 'unknown version'})",
        )

    def discover(self):
        return [
            {
                "label": f"{c['name']} (Home Assistant {c['version']})" if c.get("version") else c["name"],
                "values": {"url": c["url"]},
            }
            for c in discover_instances()
        ]
