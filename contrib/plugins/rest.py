"""REST: an HTTP request to any URL — webhooks, device APIs, anything that speaks HTTP."""

import requests

from cinefin.plugins import RUN_TIMEOUT, CommandProvider, Field, register


@register
class RestProvider(CommandProvider):
    id = "rest"
    label = "REST"
    icon = "globe"
    description = "An HTTP request to any URL"
    fields = [
        Field("method", type="select", choices=("GET", "POST", "PUT", "PATCH", "DELETE"), default="GET"),
        Field("url", "URL", required=True, placeholder="http://host/api/..."),
        Field("headers", "Headers (JSON)", type="json", placeholder='{"Authorization": "Bearer ..."}'),
        Field("body", "Body (JSON)", type="json", placeholder='{"key": "value"}'),
    ]

    def run(self, config, settings):
        url = (config.get("url") or "").strip()
        if not url:
            return False, "no URL configured", ""
        method = (config.get("method") or "GET").upper()
        try:
            response = requests.request(
                method,
                url,
                headers=config.get("headers") or {},
                json=config.get("body") or None,
                timeout=RUN_TIMEOUT,
            )
            return response.ok, f"HTTP {response.status_code}", response.text
        except requests.RequestException as exc:
            return False, exc.__class__.__name__, str(exc)

    def summary(self, config):
        return f"{config.get('method') or 'GET'} {config.get('url') or ''}".strip()
