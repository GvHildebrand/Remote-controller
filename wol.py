"""Wake-on-LAN helper: sends magic packets to power on TVs over Wi-Fi.

On some sandboxes (notably iOS apps like a-Shell) UDP broadcast is blocked.
As a workaround we also send the magic packet as a unicast directly to the
TV's last-known IP — most smart TVs will accept a directed magic packet on
the wire even though that isn't the textbook WoL address.
"""
from __future__ import annotations

import ipaddress
import re
import socket

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$")


def _normalize(mac: str) -> bytes:
    cleaned = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    return bytes.fromhex(cleaned)


def _subnet_broadcast(ip: str) -> str | None:
    try:
        return str(ipaddress.IPv4Network(f"{ip}/24", strict=False).broadcast_address)
    except (ValueError, ipaddress.AddressValueError):
        return None


def send_magic_packet(
    mac: str,
    broadcast: str = "255.255.255.255",
    port: int = 9,
    target_ip: str | None = None,
) -> list[str]:
    """Send a WoL magic packet. Returns the list of destinations attempted.

    Attempts, in order: global broadcast, subnet broadcast (derived from
    target_ip), and unicast to target_ip on UDP 7 and 9. Continues past
    per-destination failures so a blocked broadcast doesn't prevent the
    unicast attempt from reaching the TV.
    """
    if not MAC_RE.match(mac):
        raise ValueError(f"Invalid MAC address: {mac!r}")

    payload = b"\xff" * 6 + _normalize(mac) * 16
    destinations: list[tuple[str, int, bool]] = []

    for p in {port, 7, 9}:
        destinations.append((broadcast, p, True))

    if target_ip:
        subnet_bcast = _subnet_broadcast(target_ip)
        if subnet_bcast and subnet_bcast != broadcast:
            for p in {port, 7, 9}:
                destinations.append((subnet_bcast, p, True))
        for p in {port, 7, 9}:
            destinations.append((target_ip, p, False))

    attempted: list[str] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr, p, _is_broadcast in destinations:
            try:
                sock.sendto(payload, (addr, p))
                attempted.append(f"{addr}:{p}")
            except OSError:
                continue
    if not attempted:
        raise OSError("All WoL sends failed (sandbox may block UDP)")
    return attempted
