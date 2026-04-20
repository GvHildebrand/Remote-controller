"""TV discovery on the local Wi-Fi network.

Two strategies are used, in order:
1. SSDP (multicast). Fast and brand-agnostic, but blocked in sandboxed
   environments like iOS a-Shell (OSError 65 / 49 / 50 on sendto).
2. Subnet port scan (unicast). TCP-probes each host on the local /24 for
   well-known TV control ports, then fingerprints responses. Slower but
   works in restrictive sandboxes.
"""
from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import Iterable
from urllib.parse import urlparse

import requests

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_TIMEOUT = 3

SEARCH_TARGETS = [
    "urn:dial-multiscreen-org:service:dial:1",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "urn:samsung.com:device:RemoteControlReceiver:1",
    "roku:ecp",
    "ssdp:all",
]

TV_HINTS = re.compile(
    r"(tv|television|bravia|webos|tizen|roku|chromecast|aquos|vizio|philips)",
    re.IGNORECASE,
)

BRAND_PATTERNS = [
    ("samsung", re.compile(r"samsung|tizen", re.IGNORECASE)),
    ("lg", re.compile(r"\blg\b|webos", re.IGNORECASE)),
    ("sony", re.compile(r"sony|bravia", re.IGNORECASE)),
    ("roku", re.compile(r"roku", re.IGNORECASE)),
    ("vizio", re.compile(r"vizio", re.IGNORECASE)),
    ("philips", re.compile(r"philips", re.IGNORECASE)),
    ("chromecast", re.compile(r"chromecast|google cast", re.IGNORECASE)),
]


@dataclass
class DiscoveredTV:
    ip: str
    name: str = ""
    brand: str = "generic"
    model: str = ""
    mac: str = ""
    location: str = ""
    server: str = ""
    usn: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _ssdp_search(target: str) -> list[str]:
    message = (
        f"M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        f'MAN: "ssdp:discover"\r\n'
        f"MX: 2\r\n"
        f"ST: {target}\r\n\r\n"
    ).encode()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    except OSError:
        return []

    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except OSError:
        pass
    sock.settimeout(SSDP_TIMEOUT)
    responses: list[str] = []
    try:
        try:
            sock.sendto(message, (SSDP_ADDR, SSDP_PORT))
        except OSError:
            # Multicast blocked (iOS a-Shell sandbox, some VPNs). Caller
            # will fall back to the unicast subnet scan.
            return []
        while True:
            try:
                data, _ = sock.recvfrom(8192)
                responses.append(data.decode("utf-8", errors="ignore"))
            except socket.timeout:
                break
            except OSError:
                break
    finally:
        sock.close()
    return responses


def _get_local_ip() -> str:
    """Best-effort local interface IP without requiring multicast."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return ""


def _probe_port(ip: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _identify_roku(ip: str) -> DiscoveredTV | None:
    try:
        response = requests.get(f"http://{ip}:8060/query/device-info", timeout=2)
    except requests.RequestException:
        return None
    if not response.ok:
        return None
    name = re.search(r"<friendly-device-name>([^<]+)</friendly-device-name>", response.text)
    if not name:
        name = re.search(r"<user-device-name>([^<]+)</user-device-name>", response.text)
    model = re.search(r"<model-name>([^<]+)</model-name>", response.text)
    return DiscoveredTV(
        ip=ip,
        brand="roku",
        name=(name.group(1) if name else f"Roku @ {ip}"),
        model=(model.group(1) if model else ""),
    )


def _identify_samsung(ip: str) -> DiscoveredTV | None:
    for port in (8001, 8002):
        if not _probe_port(ip, port):
            continue
        try:
            response = requests.get(f"http://{ip}:8001/api/v2/", timeout=2)
            if response.ok:
                try:
                    device = response.json().get("device", {})
                    return DiscoveredTV(
                        ip=ip,
                        brand="samsung",
                        name=device.get("name") or f"Samsung TV @ {ip}",
                        model=device.get("modelName", ""),
                    )
                except ValueError:
                    pass
        except requests.RequestException:
            pass
        return DiscoveredTV(ip=ip, brand="samsung", name=f"Samsung TV @ {ip}")
    return None


def _identify_lg(ip: str) -> DiscoveredTV | None:
    if _probe_port(ip, 3000) or _probe_port(ip, 3001):
        return DiscoveredTV(ip=ip, brand="lg", name=f"LG TV @ {ip}")
    return None


def _identify_sony(ip: str) -> DiscoveredTV | None:
    try:
        response = requests.post(
            f"http://{ip}/sony/system",
            json={
                "method": "getSystemInformation",
                "id": 1,
                "params": [],
                "version": "1.0",
            },
            timeout=2,
        )
        if response.ok:
            data = response.json()
            if "result" in data and data["result"]:
                info = data["result"][0]
                return DiscoveredTV(
                    ip=ip,
                    brand="sony",
                    name=info.get("name", f"Sony TV @ {ip}"),
                    model=info.get("model", ""),
                )
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


_SCAN_FINGERPRINTS: list[tuple[int, callable]] = [
    (8060, _identify_roku),
    (8001, _identify_samsung),
    (3000, _identify_lg),
    (80, _identify_sony),
]


def _subnet_scan() -> list[DiscoveredTV]:
    local_ip = _get_local_ip()
    if not local_ip:
        return []
    try:
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
    except ValueError:
        return []

    hosts = [str(h) for h in network.hosts() if str(h) != local_ip]

    found: dict[str, DiscoveredTV] = {}

    def work(ip_port_fn: tuple[str, int, callable]) -> DiscoveredTV | None:
        ip, port, identify = ip_port_fn
        if not _probe_port(ip, port):
            return None
        return identify(ip)

    tasks: list[tuple[str, int, callable]] = []
    for ip in hosts:
        for port, identify in _SCAN_FINGERPRINTS:
            tasks.append((ip, port, identify))

    with concurrent.futures.ThreadPoolExecutor(max_workers=80) as pool:
        for result in pool.map(work, tasks, timeout=15):
            if result and result.ip not in found:
                found[result.ip] = result
    return list(found.values())


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in raw.splitlines()[1:]:
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().upper()] = value.strip()
    return headers


def _detect_brand(text: str) -> str:
    for brand, pattern in BRAND_PATTERNS:
        if pattern.search(text):
            return brand
    return "generic"


def _fetch_device_description(location: str) -> tuple[str, str, str]:
    try:
        response = requests.get(location, timeout=2)
        response.raise_for_status()
    except requests.RequestException:
        return "", "", ""

    body = response.text
    name, model = "", ""
    try:
        root = ET.fromstring(body)
        ns = {"u": "urn:schemas-upnp-org:device-1-0"}
        device = root.find("u:device", ns) or root.find(".//{*}device")
        if device is not None:
            friendly = device.find("u:friendlyName", ns) or device.find(".//{*}friendlyName")
            model_el = device.find("u:modelName", ns) or device.find(".//{*}modelName")
            if friendly is not None and friendly.text:
                name = friendly.text
            if model_el is not None and model_el.text:
                model = model_el.text
    except ET.ParseError:
        pass

    return name, model, body


def _lookup_mac(ip: str) -> str:
    try:
        socket.create_connection((ip, 80), timeout=0.5).close()
    except OSError:
        pass

    try:
        output = subprocess.run(
            ["ip", "neigh", "show", ip],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        output = ""

    if not output:
        try:
            with open("/proc/net/arp", "r") as fh:
                for line in fh.readlines()[1:]:
                    parts = line.split()
                    if parts and parts[0] == ip and len(parts) >= 4:
                        return parts[3] if parts[3] != "00:00:00:00:00:00" else ""
        except OSError:
            return ""

    match = re.search(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", output)
    return match.group(0).lower() if match else ""


def discover_tvs() -> list[DiscoveredTV]:
    """Discover TVs on the local network. Returns a de-duplicated list."""
    seen: dict[str, DiscoveredTV] = {}

    for target in SEARCH_TARGETS:
        for raw in _ssdp_search(target):
            headers = _parse_headers(raw)
            location = headers.get("LOCATION", "")
            server = headers.get("SERVER", "")
            usn = headers.get("USN", "")
            st = headers.get("ST", "")

            if not location:
                continue

            parsed = urlparse(location)
            ip = parsed.hostname or ""
            if not ip:
                continue

            name, model, body = _fetch_device_description(location)
            fingerprint = " ".join([server, st, usn, name, model, body[:4000]])

            if not TV_HINTS.search(fingerprint) and "roku" not in server.lower():
                continue

            tv = seen.get(ip)
            if tv is None:
                tv = DiscoveredTV(ip=ip)
                seen[ip] = tv

            tv.name = tv.name or name or ip
            tv.model = tv.model or model
            tv.location = tv.location or location
            tv.server = tv.server or server
            tv.usn = tv.usn or usn
            brand = _detect_brand(fingerprint)
            if brand != "generic" or tv.brand == "":
                tv.brand = brand

    if not seen:
        for tv in _subnet_scan():
            seen[tv.ip] = tv

    for tv in seen.values():
        tv.mac = _lookup_mac(tv.ip)

    return list(seen.values())


def manual_tv(ip: str, brand: str = "generic", mac: str = "") -> DiscoveredTV:
    """Build a DiscoveredTV from manual input (fallback when SSDP misses)."""
    return DiscoveredTV(
        ip=ip,
        brand=brand or "generic",
        name=f"TV @ {ip}",
        mac=mac or _lookup_mac(ip),
    )
