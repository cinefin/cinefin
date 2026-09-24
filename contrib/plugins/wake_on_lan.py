"""Wake-on-LAN: send a magic packet to power on a projector, AV receiver or playout box before a show."""

import re
import socket

from cinefin.plugins import CommandProvider, Field, register

_MAC_RE = re.compile(r"^([0-9a-f]{2}[:-]?){5}[0-9a-f]{2}$", re.IGNORECASE)


@register
class WakeOnLan(CommandProvider):
    id = "wake_on_lan"
    label = "Wake-on-LAN"
    icon = "power"
    description = "Send a Wake-on-LAN magic packet to a device on the local network"
    fields = [
        Field("mac", "MAC address", required=True, placeholder="aa:bb:cc:dd:ee:ff"),
        Field(
            "broadcast",
            "Broadcast address",
            default="255.255.255.255",
            placeholder="255.255.255.255",
            help="Use the subnet broadcast (e.g. 192.168.1.255) if the global one is filtered",
        ),
        Field("port", type="number", default=9, help="Usually 9 (sometimes 7)"),
    ]

    def run(self, config, settings):
        mac = (config.get("mac") or "").strip()
        if not _MAC_RE.match(mac):
            return False, "invalid MAC address", mac
        packet = b"\xff" * 6 + bytes.fromhex(re.sub(r"[:-]", "", mac)) * 16
        target = ((config.get("broadcast") or "255.255.255.255").strip(), int(config.get("port") or 9))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, target)
        return True, "packet sent", f"magic packet for {mac} → {target[0]}:{target[1]}"

    def summary(self, config):
        return (config.get("mac") or "").lower()
