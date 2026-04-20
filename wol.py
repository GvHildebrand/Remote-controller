"""Wake-on-LAN helper: sends magic packets to power on TVs over Wi-Fi."""
from __future__ import annotations

import re
import socket

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$")


def _normalize(mac: str) -> bytes:
    cleaned = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    return bytes.fromhex(cleaned)


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a WoL magic packet to the given MAC on the broadcast address."""
    if not MAC_RE.match(mac):
        raise ValueError(f"Invalid MAC address: {mac!r}")

    payload = b"\xff" * 6 + _normalize(mac) * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for p in {port, 7, 9}:
            sock.sendto(payload, (broadcast, p))
