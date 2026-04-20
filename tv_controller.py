"""Brand-specific TV control. Wake-on-LAN is used for power-on across brands.

For richer control (volume, channel, source) each brand uses its own protocol:
- Samsung (Tizen): WebSocket on port 8002 with a base64-encoded key name
- LG (WebOS): WebSocket on port 3000/3001, requires a client key
- Roku: HTTP External Control Protocol (ECP) on port 8060
"""
from __future__ import annotations

import base64
import json
import socket
from dataclasses import dataclass
from typing import Callable

import requests

from wol import send_magic_packet


KEY_ALIASES = {
    "power": {
        "samsung": "KEY_POWER",
        "lg": "POWER",
        "roku": "Power",
    },
    "volume_up": {
        "samsung": "KEY_VOLUP",
        "lg": "VOLUMEUP",
        "roku": "VolumeUp",
    },
    "volume_down": {
        "samsung": "KEY_VOLDOWN",
        "lg": "VOLUMEDOWN",
        "roku": "VolumeDown",
    },
    "mute": {
        "samsung": "KEY_MUTE",
        "lg": "MUTE",
        "roku": "VolumeMute",
    },
    "channel_up": {
        "samsung": "KEY_CHUP",
        "lg": "CHANNELUP",
        "roku": "ChannelUp",
    },
    "channel_down": {
        "samsung": "KEY_CHDOWN",
        "lg": "CHANNELDOWN",
        "roku": "ChannelDown",
    },
    "home": {
        "samsung": "KEY_HOME",
        "lg": "HOME",
        "roku": "Home",
    },
    "back": {
        "samsung": "KEY_RETURN",
        "lg": "BACK",
        "roku": "Back",
    },
    "ok": {
        "samsung": "KEY_ENTER",
        "lg": "ENTER",
        "roku": "Select",
    },
    "up": {"samsung": "KEY_UP", "lg": "UP", "roku": "Up"},
    "down": {"samsung": "KEY_DOWN", "lg": "DOWN", "roku": "Down"},
    "left": {"samsung": "KEY_LEFT", "lg": "LEFT", "roku": "Left"},
    "right": {"samsung": "KEY_RIGHT", "lg": "RIGHT", "roku": "Right"},
}


@dataclass
class CommandResult:
    ok: bool
    method: str
    detail: str = ""


def power_on(ip: str, mac: str, broadcast: str = "255.255.255.255") -> CommandResult:
    """Turn the TV on. Wake-on-LAN is the only reliable cross-brand method
    when the TV is off, since its HTTP/WebSocket stack is down."""
    if not mac:
        return CommandResult(
            ok=False,
            method="wol",
            detail="No MAC address known for this TV. Connect once while the TV is on so the router learns its MAC, then retry.",
        )
    try:
        send_magic_packet(mac, broadcast=broadcast)
    except (OSError, ValueError) as exc:
        return CommandResult(ok=False, method="wol", detail=str(exc))
    return CommandResult(ok=True, method="wol", detail=f"Magic packet sent to {mac}")


def send_key(brand: str, ip: str, key: str, token: str = "", client_key: str = "") -> CommandResult:
    """Send a key press to a TV that's already on."""
    brand = (brand or "generic").lower()
    handler = _HANDLERS.get(brand, _send_generic)
    return handler(ip=ip, key=key, token=token, client_key=client_key)


def _resolve_key(brand: str, key: str) -> str:
    entry = KEY_ALIASES.get(key.lower())
    if entry and brand in entry:
        return entry[brand]
    return key


def _send_roku(ip: str, key: str, **_: str) -> CommandResult:
    native = _resolve_key("roku", key)
    url = f"http://{ip}:8060/keypress/{native}"
    try:
        response = requests.post(url, timeout=3)
        response.raise_for_status()
    except requests.RequestException as exc:
        return CommandResult(ok=False, method="roku-ecp", detail=str(exc))
    return CommandResult(ok=True, method="roku-ecp", detail=native)


def _send_samsung(ip: str, key: str, token: str = "", **_: str) -> CommandResult:
    try:
        import websocket  # type: ignore
    except ImportError:
        return CommandResult(ok=False, method="samsung-ws", detail="websocket-client not installed")

    native = _resolve_key("samsung", key)
    name = base64.b64encode(b"WiFiRemote").decode()
    suffix = f"&token={token}" if token else ""
    url = f"wss://{ip}:8002/api/v2/channels/samsung.remote.control?name={name}{suffix}"

    try:
        ws = websocket.create_connection(url, timeout=5, sslopt={"cert_reqs": 0})
    except Exception as exc:  # noqa: BLE001 - websocket raises many types
        return CommandResult(ok=False, method="samsung-ws", detail=str(exc))

    try:
        ws.recv()  # connection ACK / token message
        payload = {
            "method": "ms.remote.control",
            "params": {
                "Cmd": "Click",
                "DataOfCmd": native,
                "Option": "false",
                "TypeOfRemote": "SendRemoteKey",
            },
        }
        ws.send(json.dumps(payload))
    finally:
        ws.close()
    return CommandResult(ok=True, method="samsung-ws", detail=native)


def _send_lg(ip: str, key: str, client_key: str = "", **_: str) -> CommandResult:
    try:
        import websocket  # type: ignore
    except ImportError:
        return CommandResult(ok=False, method="lg-webos", detail="websocket-client not installed")

    native = _resolve_key("lg", key)
    url = f"ws://{ip}:3000"
    try:
        ws = websocket.create_connection(url, timeout=5)
    except Exception as exc:  # noqa: BLE001
        return CommandResult(ok=False, method="lg-webos", detail=str(exc))

    try:
        handshake = {
            "type": "register",
            "id": "register_0",
            "payload": {
                "pairingType": "PROMPT",
                "client-key": client_key,
                "manifest": {"permissions": ["CONTROL_INPUT_TV", "CONTROL_POWER"]},
            },
        }
        ws.send(json.dumps(handshake))
        ws.recv()
        command = {
            "type": "button",
            "id": "btn_0",
            "payload": {"name": native},
        }
        ws.send(json.dumps(command))
    finally:
        ws.close()
    return CommandResult(ok=True, method="lg-webos", detail=native)


def _send_generic(ip: str, key: str, **_: str) -> CommandResult:
    return CommandResult(
        ok=False,
        method="generic",
        detail=(
            "TV brand unknown — key presses require a brand-specific protocol. "
            "Power-on via Wake-on-LAN still works if a MAC address is known."
        ),
    )


_HANDLERS: dict[str, Callable[..., CommandResult]] = {
    "roku": _send_roku,
    "samsung": _send_samsung,
    "lg": _send_lg,
}


def reachable(ip: str, port: int = 80, timeout: float = 1.0) -> bool:
    """Quick connectivity check — TVs answer on HTTP/SSDP ports when on."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False
