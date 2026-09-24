"""Yamaha MusicCast: control a Yamaha AV receiver over its Extended Control (YXC) HTTP API.

Power/input, volume/mute, sound programs and scene recall, plus a raw-path escape
hatch — all plain GETs to http://<host>/YamahaExtendedControl/v1/. No cloud, no
new dependency; the receiver answers on the LAN.
"""

import socket

import requests

from cinefin.plugins import CommandProvider, Field, register

RUN_TIMEOUT_S = 5
PROBE_TIMEOUT_S = 3
ZONES = ("main", "zone2", "zone3", "zone4")
#: Actions whose value names a target the receiver can't guess.
NEEDS_VALUE = {"input", "sound_program", "scene"}
_TRUTHY = {"1", "true", "on", "yes"}


def _base(settings):
    host = (settings.get("host") or "").strip()
    if not host:
        return ""
    return f"http://{host}:{int(settings.get('port') or 80)}/YamahaExtendedControl/v1"


def _get(url, timeout):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _path_for(action, zone, value):
    """The YXC request path (without the base) for a structured action."""
    v = (value or "").strip()
    if action == "power":
        return f"/{zone}/setPower?power={v or 'on'}"
    if action == "input":
        return f"/{zone}/setInput?input={v}"
    if action == "volume":
        return f"/{zone}/setVolume?volume={v.lower() if v.lower() in ('up', 'down') else int(v)}"
    if action == "mute":
        return f"/{zone}/setMute?enable={'true' if v.lower() in _TRUTHY else 'false'}"
    if action == "sound_program":
        return f"/{zone}/setSoundProgram?program={v}"
    if action == "scene":
        return f"/{zone}/recallScene?num={int(v)}"
    if action == "raw":
        return "/" + v.lstrip("/")
    raise ValueError(f"unknown action {action!r}")


def _ssdp_media_renderers(timeout=2):
    """IPs of UPnP MediaRenderers answering an SSDP M-SEARCH (Yamaha ones among them)."""
    message = (
        b"M-SEARCH * HTTP/1.1\r\n"
        b"HOST: 239.255.255.250:1900\r\n"
        b'MAN: "ssdp:discover"\r\n'
        b"MX: 1\r\n"
        b"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
    )
    hosts = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        sock.sendto(message, ("239.255.255.250", 1900))
        try:
            while True:
                _data, addr = sock.recvfrom(2048)
                hosts.add(addr[0])
        except TimeoutError:
            pass
    return hosts


@register
class YamahaMusicCast(CommandProvider):
    id = "yamaha_musiccast"
    label = "Yamaha MusicCast"
    icon = "speaker"
    description = "Control a Yamaha AV receiver (power, input, volume, sound modes, scenes)"
    fields = [
        Field(
            "action",
            type="select",
            required=True,
            choices=("power", "input", "volume", "mute", "sound_program", "scene", "raw"),
        ),
        Field("zone", type="select", default="main", choices=ZONES),
        Field(
            "value",
            scoped_by="action",
            placeholder="on",
            help=(
                "power: on/standby/toggle · input: hdmi1 · volume: a number or up/down · "
                "mute: true/false · sound_program: movie · scene: 1 · raw: main/setPower?power=on"
            ),
        ),
    ]
    settings = [
        Field(
            "host",
            "Receiver host",
            required=True,
            placeholder="192.168.1.20",
            help="IP or hostname of the receiver, reachable from this server — or let Discover find it.",
        ),
        Field("port", type="number", default=80),
    ]

    def run(self, config, settings):
        base = _base(settings)
        if not base:
            return False, "Yamaha receiver is not configured (Settings → Plugins)", ""
        action = (config.get("action") or "").strip()
        zone = (config.get("zone") or "main").strip() or "main"
        if action in NEEDS_VALUE and not (config.get("value") or "").strip():
            return False, f"{action.replace('_', ' ')} needs a value", ""
        try:
            path = _path_for(action, zone, config.get("value"))
        except (ValueError, TypeError) as exc:
            return False, f"invalid value for {action}", str(exc)
        try:
            response = requests.get(base + path, timeout=RUN_TIMEOUT_S)
            response.raise_for_status()
            code = response.json().get("response_code")
        except requests.RequestException as exc:
            return False, exc.__class__.__name__, str(exc)
        except ValueError:
            return False, "invalid response from receiver", response.text[:200]
        ok = code == 0
        return ok, "ok" if ok else f"response_code {code}", response.text

    def summary(self, config):
        action = (config.get("action") or "").replace("_", " ")
        if not action:
            return ""
        value = config.get("value") or ""
        target = f"{action} → {value}" if value else action
        zone = config.get("zone") or "main"
        return target if zone == "main" else f"{zone}: {target}"

    def suggestions(self, settings):
        base = _base(settings)
        if not base:
            raise ValueError("Yamaha receiver is not configured — set it up in Settings → Plugins")
        try:
            features = _get(f"{base}/getFeatures", PROBE_TIMEOUT_S)
        except requests.RequestException as exc:
            raise ValueError(f"Receiver is not reachable ({exc.__class__.__name__})") from exc

        values = [
            {"value": "on", "scope": "power"},
            {"value": "standby", "scope": "power"},
            {"value": "toggle", "scope": "power"},
            {"value": "true", "label": "mute on", "scope": "mute"},
            {"value": "false", "label": "mute off", "scope": "mute"},
            {"value": "up", "scope": "volume"},
            {"value": "down", "scope": "volume"},
        ]
        inputs, programs, scene_num = set(), [], 0
        for zone in features.get("zone", []):
            inputs.update(zone.get("input_list") or [])
            if zone.get("id") == "main":
                programs = zone.get("sound_program_list") or []
                scene_num = zone.get("scene_num") or 0
        values += [{"value": name, "scope": "input"} for name in sorted(inputs)]
        values += [{"value": name, "scope": "sound_program"} for name in programs]
        values += [{"value": str(n), "scope": "scene"} for n in range(1, (scene_num or 4) + 1)]
        return {"value": values}

    def test_settings(self, settings):
        base = _base(settings)
        if not base:
            return False, "Enter the receiver's host first."
        try:
            info = _get(f"{base}/system/getDeviceInfo", PROBE_TIMEOUT_S)
        except requests.RequestException as exc:
            return False, f"{exc.__class__.__name__}: could not reach the receiver"
        if info.get("response_code") != 0:
            return False, f"receiver returned response_code {info.get('response_code')}"
        model = info.get("model_name") or "Yamaha receiver"
        version = info.get("system_version")
        return True, f"Connected to {model}" + (f" (firmware {version})" if version else "")

    def discover(self):
        candidates = []
        for host in sorted(_ssdp_media_renderers()):
            try:
                info = _get(f"http://{host}/YamahaExtendedControl/v1/system/getDeviceInfo", PROBE_TIMEOUT_S)
            except requests.RequestException:
                continue
            if info.get("response_code") == 0:
                model = info.get("model_name") or host
                candidates.append({"label": f"{model} ({host})", "values": {"host": host}})
        return candidates
