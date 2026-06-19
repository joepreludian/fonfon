"""Boundary probes for OS identity and networking. The only code here that
touches the real system; everything is injectable for tests."""

import json
import platform
import urllib.request
from collections.abc import Callable

from fonfon.system._run import run as _default_run

OS_RELEASE_PATH = "/etc/os-release"
PUBLIC_IP_URL = "https://api.ipify.org"
PUBLIC_IP_TIMEOUT = 3


def parse_os_release(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"')
    return result


def read_os_release(path: str = OS_RELEASE_PATH) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as handle:
            return parse_os_release(handle.read())
    except OSError:
        return {}


def machine() -> str:
    return platform.machine()


def interfaces(run: Callable = _default_run) -> dict[str, str]:
    """Map interface name -> first IPv4 address, excluding loopback."""
    proc = run(["ip", "-json", "addr", "show"])
    if proc.returncode != 0:
        return {}
    result: dict[str, str] = {}
    for iface in json.loads(proc.stdout or "[]"):
        name = iface.get("ifname")
        if name == "lo":
            continue
        for addr in iface.get("addr_info", []):
            if addr.get("family") == "inet":
                result[name] = addr["local"]
                break
    return result


def _urlopen(url: str, timeout: int):
    return urllib.request.urlopen(url, timeout=timeout)


def public_ip(
    opener: Callable = _urlopen, timeout: int = PUBLIC_IP_TIMEOUT
) -> str | None:
    """Best-effort external IP. Returns None if unreachable."""
    try:
        with opener(PUBLIC_IP_URL, timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None
