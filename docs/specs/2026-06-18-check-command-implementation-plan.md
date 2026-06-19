# `fonfon check` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `fonfon check`, a read-only system-readiness report, on a layered architecture (CLI → fluent domain services → policy use-case → presentation DTO → console/json renderers).

**Architecture:** Five fluent domain services each probe one area and return plain-fact DTOs (no policy). A `run_check()` use-case composes them and applies status policy into a single `CheckReport`. Renderers consume only `CheckReport`. All OS I/O is quarantined behind injectable boundary adapters in `system/` — that is the unit-test seam. Package detection is a Strategy keyed on distro (Debian/dpkg only for now).

**Tech Stack:** Python 3.14, click, rich, pydantic (new runtime dep), pytest. Target-side binaries assumed present on Debian: `systemctl`, `dpkg-query`, `ip` (iproute2), `docker`.

**Reference spec:** `docs/specs/2026-06-18-check-command-architecture-design.md` — read it for full rationale, the status-policy table, and the console mockup.

**Conventions (from CLAUDE.md):** Conventional Commits. Run `pre-commit` before any commit. No "Co-authored-by: Claude". Commits are authored/authorized by the maintainer — **do not commit unless told**; the maintainer will batch commits. Each new feature gets a `docs/manual` entry.

---

## Shared conventions for all tasks

- **Test location:** flat under `tests/`, mirroring the existing `tests/test_version.py` style.
- **Boundary-adapter seam:** every adapter that runs a subprocess takes a `run` callable with a real default, so tests inject a fake. The shared type:

```python
# the shape every adapter's injected runner satisfies
from subprocess import CompletedProcess
from typing import Protocol

class Runner(Protocol):
    def __call__(self, args: list[str]) -> CompletedProcess: ...
```

- **Real default runner** (define once in `system/_run.py`, reused by adapters):

```python
# src/fonfon/system/_run.py
import subprocess

DEFAULT_TIMEOUT = 10

def run(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a command, capturing text output; never raises on non-zero exit."""
    return subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=timeout
    )
```

- **Fake runner for tests** (define inline per test or in `tests/fakes.py`):

```python
# tests/fakes.py
from subprocess import CompletedProcess

def fake_runner(responses: dict[tuple[str, ...], CompletedProcess]):
    """Return a runner that maps an argv tuple to a canned CompletedProcess."""
    def _run(args, timeout=10):
        return responses[tuple(args)]
    return _run

def completed(args, returncode=0, stdout="", stderr=""):
    return CompletedProcess(args, returncode, stdout, stderr)
```

---

## Task 1: pydantic dependency + presentation DTOs

**Files:**
- Modify: `pyproject.toml` (add pydantic to `[project].dependencies`)
- Create: `src/fonfon/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Add pydantic as a runtime dependency**

In `pyproject.toml`, under `[project].dependencies`, add `"pydantic>=2.0"` after `"rich>=15.0.0",`. Then run:

```bash
uv sync
```
Expected: pydantic resolves and installs; `uv.lock` updates.

- [ ] **Step 2: Write the failing test for the DTOs**

```python
# tests/test_models.py
from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus


def _report(*statuses: CheckStatus) -> CheckReport:
    items = [CheckItem(key=f"k{i}", label=f"L{i}", status=s, detail=None)
             for i, s in enumerate(statuses)]
    return CheckReport(sections=[CheckSection(title="S", items=items)])


def test_status_enum_values_are_lowercase_strings():
    assert CheckStatus.OK.value == "ok"
    assert CheckStatus.FAIL.value == "fail"


def test_report_ok_true_when_no_fail():
    report = _report(CheckStatus.OK, CheckStatus.WARN, CheckStatus.INFO, CheckStatus.SKIP)
    assert report.ok is True


def test_report_ok_false_when_any_fail():
    report = _report(CheckStatus.OK, CheckStatus.FAIL)
    assert report.ok is False


def test_report_serializes_to_json():
    report = _report(CheckStatus.OK)
    data = report.model_dump_json()
    assert '"status":"ok"' in data.replace(" ", "")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.models'`.

- [ ] **Step 4: Implement `models.py`**

```python
# src/fonfon/models.py
"""Presentation DTOs for Fonfon command output.

These carry *policy* results (status) and are what the renderers and the
exit-code logic consume. Domain services return their own fact DTOs; the
per-command use-case maps those into these types.
"""

from enum import Enum

from pydantic import BaseModel


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"
    SKIP = "skip"


class CheckItem(BaseModel):
    key: str
    label: str
    status: CheckStatus
    detail: str | None = None


class CheckSection(BaseModel):
    title: str
    items: list[CheckItem]


class CheckReport(BaseModel):
    sections: list[CheckSection]

    @property
    def ok(self) -> bool:
        """True unless any item failed. WARN/INFO/SKIP do not fail the gate."""
        return not any(
            item.status is CheckStatus.FAIL
            for section in self.sections
            for item in section.items
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: 4 passed.

---

## Task 2: system probes (OS, network)

**Files:**
- Create: `src/fonfon/system/__init__.py` (empty)
- Create: `src/fonfon/system/_run.py` (see Shared conventions — the `run` default)
- Create: `src/fonfon/system/probes.py`
- Test: `tests/test_system_probes.py`

`probes.py` holds the non-command-object boundary functions. Each takes injectable seams with real defaults.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_system_probes.py
from fonfon.system import probes
from tests.fakes import completed


def test_parse_os_release_extracts_id_and_pretty_name():
    text = 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nID=debian\nVERSION_ID="12"\n'
    info = probes.parse_os_release(text)
    assert info["ID"] == "debian"
    assert info["PRETTY_NAME"] == "Debian GNU/Linux 12 (bookworm)"


def test_interfaces_parses_ip_json_addr():
    ip_json = (
        '[{"ifname":"lo","addr_info":[{"family":"inet","local":"127.0.0.1"}]},'
        '{"ifname":"eth0","addr_info":[{"family":"inet","local":"203.0.113.5"}]},'
        '{"ifname":"tailscale0","addr_info":[{"family":"inet","local":"100.101.102.103"}]}]'
    )
    run = lambda args, timeout=10: completed(args, stdout=ip_json)
    result = probes.interfaces(run=run)
    assert result == {"eth0": "203.0.113.5", "tailscale0": "100.101.102.103"}  # lo excluded


def test_public_ip_returns_stripped_body():
    opener = lambda url, timeout: _FakeResp(b"203.0.113.5\n")
    assert probes.public_ip(opener=opener) == "203.0.113.5"


def test_public_ip_returns_none_on_error():
    def opener(url, timeout):
        raise OSError("no network")
    assert probes.public_ip(opener=opener) is None


class _FakeResp:
    def __init__(self, body): self._body = body
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *a): return False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_system_probes.py -v`
Expected: FAIL — module/attribute not found.

- [ ] **Step 3: Implement `probes.py`**

```python
# src/fonfon/system/probes.py
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


def public_ip(opener: Callable = _urlopen, timeout: int = PUBLIC_IP_TIMEOUT) -> str | None:
    """Best-effort external IP. Returns None if unreachable."""
    try:
        with opener(PUBLIC_IP_URL, timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_system_probes.py -v`
Expected: all passed.

Also create empty `src/fonfon/system/__init__.py` and `tests/fakes.py` (from Shared conventions) if not present, and an empty `tests/__init__.py` is NOT needed (pytest rootdir import). Verify `from tests.fakes import ...` resolves; if not, add `tests/__init__.py` (empty).

---

## Task 3: command adapters (Systemctl, Dpkg, DockerCli)

**Files:**
- Create: `src/fonfon/system/systemctl.py`
- Create: `src/fonfon/system/dpkg.py`
- Create: `src/fonfon/system/docker_cli.py`
- Test: `tests/test_systemctl.py`, `tests/test_dpkg.py`, `tests/test_docker_cli.py`

Each adapter is a small class taking `run` via constructor (default `_default_run`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_systemctl.py
from fonfon.system.systemctl import Systemctl
from tests.fakes import completed


def _sc(**outcomes):
    # outcomes maps the systemctl subcommand verb -> CompletedProcess
    def run(args, timeout=10):
        verb = args[1]  # ["systemctl", "<verb>", "<unit>"]
        return outcomes[verb]
    return Systemctl(run=run)


def test_is_enabled_true_on_zero_exit_and_enabled():
    sc = _sc(**{"is-enabled": completed([], 0, "enabled\n")})
    assert sc.is_enabled("ssh") is True


def test_is_enabled_false_on_disabled():
    sc = _sc(**{"is-enabled": completed([], 1, "disabled\n")})
    assert sc.is_enabled("docker") is False


def test_is_active_true_on_active():
    sc = _sc(**{"is-active": completed([], 0, "active\n")})
    assert sc.is_active("ssh") is True


def test_exists_false_when_not_found():
    sc = _sc(**{"is-enabled": completed([], 1, "", "Failed to get unit ... not-found")})
    assert sc.exists("nope") is False
```

```python
# tests/test_dpkg.py
from fonfon.system.dpkg import Dpkg
from tests.fakes import completed


def test_query_installed_with_version():
    out = "install ok installed 1.9.13p3-1+deb12u1\n"
    dpkg = Dpkg(run=lambda args, timeout=10: completed(args, 0, out))
    state = dpkg.query("sudo")
    assert state.installed is True
    assert state.version == "1.9.13p3-1+deb12u1"
    assert state.name == "sudo"


def test_query_not_installed_returns_false_none():
    dpkg = Dpkg(run=lambda args, timeout=10: completed(args, 1, "", "no packages found"))
    state = dpkg.query("docker-ce")
    assert state.installed is False
    assert state.version is None
```

```python
# tests/test_docker_cli.py
from fonfon.system.docker_cli import DockerCli
from tests.fakes import completed


def test_inspect_container_returns_none_when_absent():
    docker = DockerCli(run=lambda args, timeout=10: completed(args, 1, "", "No such object"))
    assert docker.inspect_container("traefik") is None


def test_inspect_container_parses_json():
    payload = '[{"Name":"/traefik","NetworkSettings":{}}]'
    docker = DockerCli(run=lambda args, timeout=10: completed(args, 0, payload))
    data = docker.inspect_container("traefik")
    assert data["Name"] == "/traefik"
```

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_systemctl.py tests/test_dpkg.py tests/test_docker_cli.py -v` → FAIL (modules missing).

- [ ] **Step 3: Implement the adapters**

```python
# src/fonfon/system/systemctl.py
from collections.abc import Callable
from fonfon.system._run import run as _default_run


class Systemctl:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def is_enabled(self, unit: str) -> bool:
        proc = self._run(["systemctl", "is-enabled", unit])
        return proc.returncode == 0 and proc.stdout.strip() == "enabled"

    def is_active(self, unit: str) -> bool:
        proc = self._run(["systemctl", "is-active", unit])
        return proc.returncode == 0 and proc.stdout.strip() == "active"

    def exists(self, unit: str) -> bool:
        proc = self._run(["systemctl", "is-enabled", unit])
        # is-enabled prints a known state for existing units; "not-found" -> absent
        return "not-found" not in (proc.stderr + proc.stdout).lower()
```

```python
# src/fonfon/system/dpkg.py
from collections.abc import Callable
from pydantic import BaseModel
from fonfon.system._run import run as _default_run


class PackageState(BaseModel):
    name: str
    installed: bool
    version: str | None = None


class Dpkg:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def query(self, name: str) -> PackageState:
        proc = self._run(
            ["dpkg-query", "-W", "-f=${Status} ${Version}", name]
        )
        if proc.returncode != 0:
            return PackageState(name=name, installed=False, version=None)
        parts = proc.stdout.strip().split()
        # "install ok installed <version>"
        installed = parts[:3] == ["install", "ok", "installed"]
        version = parts[3] if installed and len(parts) >= 4 else None
        return PackageState(name=name, installed=installed, version=version)
```

> Note: `PackageState` lives here because `Dpkg` produces it and `PackageService` re-exports it. If a reviewer prefers it in `models.py` or `package_service.py`, that's acceptable as long as imports stay consistent across Tasks 3/5/8.

```python
# src/fonfon/system/docker_cli.py
import json
from collections.abc import Callable
from fonfon.system._run import run as _default_run


class DockerCli:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def is_available(self) -> bool:
        return self._run(["docker", "version", "--format", "{{.Server.Version}}"]).returncode == 0

    def inspect_container(self, name: str) -> dict | None:
        proc = self._run(["docker", "inspect", name])
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "[]")
        return data[0] if data else None
```

- [ ] **Step 4: Run to verify pass.** Expected: all passed.

---

## Task 4: OSService + NetworkService

**Files:**
- Create: `src/fonfon/services/__init__.py` (empty)
- Create: `src/fonfon/services/os_service.py`
- Create: `src/fonfon/services/network_service.py`
- Test: `tests/test_os_service.py`, `tests/test_network_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_os_service.py
from fonfon.services.os_service import OSService


def test_get_info_maps_pretty_name_id_and_machine():
    svc = OSService(
        read_os_release=lambda: {"PRETTY_NAME": "Debian GNU/Linux 12 (bookworm)", "ID": "debian"},
        machine=lambda: "x86_64",
    )
    info = svc.get_info()
    assert info.distro == "Debian GNU/Linux 12 (bookworm)"
    assert info.distro_id == "debian"
    assert info.architecture == "x86_64"


def test_get_info_falls_back_when_os_release_empty():
    svc = OSService(read_os_release=lambda: {}, machine=lambda: "aarch64")
    info = svc.get_info()
    assert info.distro_id == "unknown"
    assert info.architecture == "aarch64"
```

```python
# tests/test_network_service.py
from fonfon.services.network_service import NetworkService


def test_get_ips_collects_interfaces_and_public():
    svc = NetworkService(
        interfaces=lambda: {"eth0": "203.0.113.5", "tailscale0": "100.101.102.103"},
        public_ip=lambda: "203.0.113.5",
    )
    info = svc.get_ips()
    assert info.interfaces["eth0"] == "203.0.113.5"
    assert info.public_ip == "203.0.113.5"


def test_get_ips_public_none_when_unreachable():
    svc = NetworkService(interfaces=lambda: {}, public_ip=lambda: None)
    assert svc.get_ips().public_ip is None
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement services**

```python
# src/fonfon/services/os_service.py
from collections.abc import Callable
from pydantic import BaseModel
from fonfon.system import probes


class OSInfo(BaseModel):
    distro: str
    distro_id: str
    architecture: str


class OSService:
    def __init__(self, read_os_release: Callable = probes.read_os_release,
                 machine: Callable = probes.machine):
        self._read_os_release = read_os_release
        self._machine = machine

    def get_info(self) -> OSInfo:
        data = self._read_os_release()
        return OSInfo(
            distro=data.get("PRETTY_NAME", "unknown"),
            distro_id=data.get("ID", "unknown"),
            architecture=self._machine(),
        )
```

```python
# src/fonfon/services/network_service.py
from collections.abc import Callable
from pydantic import BaseModel
from fonfon.system import probes


class NetworkInfo(BaseModel):
    interfaces: dict[str, str]
    public_ip: str | None = None


class NetworkService:
    def __init__(self, interfaces: Callable = probes.interfaces,
                 public_ip: Callable = probes.public_ip):
        self._interfaces = interfaces
        self._public_ip = public_ip

    def get_ips(self) -> NetworkInfo:
        return NetworkInfo(interfaces=self._interfaces(), public_ip=self._public_ip())
```

- [ ] **Step 4: Run to verify pass.**

---

## Task 5: Package Strategy + PackageService

**Files:**
- Create: `src/fonfon/services/package_backends.py`
- Create: `src/fonfon/services/package_service.py`
- Test: `tests/test_package_backends.py`, `tests/test_package_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_package_backends.py
import pytest
from fonfon.services.package_backends import (
    DebianPackageBackend, UnsupportedDistroError, select_package_backend,
)
from fonfon.system.dpkg import PackageState


class FakeDpkg:
    def __init__(self, installed): self._installed = installed
    def query(self, name):
        if name in self._installed:
            return PackageState(name=name, installed=True, version=self._installed[name])
        return PackageState(name=name, installed=False, version=None)


def test_debian_backend_queries_via_dpkg():
    backend = DebianPackageBackend(dpkg=FakeDpkg({"sudo": "1.9.13"}))
    assert backend.query("sudo").installed is True
    assert backend.query("docker-ce").installed is False


def test_select_returns_debian_for_debian_family():
    assert isinstance(select_package_backend("debian"), DebianPackageBackend)
    assert isinstance(select_package_backend("ubuntu"), DebianPackageBackend)


def test_select_raises_for_unknown_distro():
    with pytest.raises(UnsupportedDistroError):
        select_package_backend("fedora")
```

```python
# tests/test_package_service.py
from fonfon.services.package_service import PackageService
from fonfon.system.dpkg import PackageState


class FakeBackend:
    def query(self, name):
        return PackageState(name=name, installed=(name == "sudo"), version="1" if name == "sudo" else None)


def test_for_packages_then_ensure_installed_returns_report():
    report = PackageService(FakeBackend()).for_packages(["sudo", "docker-ce"]).ensure_installed()
    by_name = {p.name: p for p in report.packages}
    assert by_name["sudo"].installed is True
    assert by_name["docker-ce"].installed is False


def test_for_packages_is_fluent():
    svc = PackageService(FakeBackend())
    assert svc.for_packages(["sudo"]) is svc
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement backends + service**

```python
# src/fonfon/services/package_backends.py
from abc import ABC, abstractmethod
from fonfon.system.dpkg import Dpkg, PackageState


class PackageBackend(ABC):
    @abstractmethod
    def query(self, name: str) -> PackageState: ...


class DebianPackageBackend(PackageBackend):
    """dpkg family: debian, ubuntu, raspbian."""

    def __init__(self, dpkg: Dpkg | None = None):
        self._dpkg = dpkg or Dpkg()

    def query(self, name: str) -> PackageState:
        return self._dpkg.query(name)


class UnsupportedDistroError(Exception):
    """Raised when no package backend is registered for a distro."""


_REGISTRY: dict[str, type[PackageBackend]] = {
    "debian": DebianPackageBackend,
    "ubuntu": DebianPackageBackend,
    "raspbian": DebianPackageBackend,
}


def select_package_backend(distro_id: str) -> PackageBackend:
    backend_cls = _REGISTRY.get(distro_id.lower())
    if backend_cls is None:
        raise UnsupportedDistroError(distro_id)
    return backend_cls()
```

```python
# src/fonfon/services/package_service.py
from collections.abc import Iterable
from pydantic import BaseModel
from fonfon.services.package_backends import PackageBackend
from fonfon.system.dpkg import PackageState


class PackageReport(BaseModel):
    packages: list[PackageState]


class PackageService:
    def __init__(self, backend: PackageBackend):
        self._backend = backend
        self._names: list[str] = []

    def for_packages(self, names: Iterable[str]) -> "PackageService":
        self._names = list(names)
        return self

    def ensure_installed(self) -> PackageReport:
        return PackageReport(packages=[self._backend.query(n) for n in self._names])
```

- [ ] **Step 4: Run to verify pass.**

---

## Task 6: SystemdService

**Files:**
- Create: `src/fonfon/services/systemd_service.py`
- Test: `tests/test_systemd_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_systemd_service.py
from fonfon.services.systemd_service import SystemdService


class FakeSystemctl:
    def __init__(self, enabled=(), active=(), present=None):
        self._enabled, self._active = set(enabled), set(active)
        self._present = set(present) if present is not None else None
    def is_enabled(self, unit): return unit in self._enabled
    def is_active(self, unit): return unit in self._active
    def exists(self, unit): return unit in self._present if self._present is not None else True


def test_get_status_reports_each_unit():
    svc = SystemdService(systemctl=FakeSystemctl(enabled={"ssh"}, active={"ssh"}))
    report = svc.for_services(["docker", "ssh"]).get_status()
    by_name = {s.name: s for s in report.services}
    assert by_name["ssh"].enabled is True and by_name["ssh"].active is True
    assert by_name["docker"].enabled is False


def test_for_services_is_fluent():
    svc = SystemdService(systemctl=FakeSystemctl())
    assert svc.for_services(["ssh"]) is svc
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

```python
# src/fonfon/services/systemd_service.py
from collections.abc import Iterable
from pydantic import BaseModel
from fonfon.system.systemctl import Systemctl


class ServiceState(BaseModel):
    name: str
    present: bool
    enabled: bool
    active: bool


class ServicesReport(BaseModel):
    services: list[ServiceState]


class SystemdService:
    def __init__(self, systemctl: Systemctl | None = None):
        self._systemctl = systemctl or Systemctl()
        self._names: list[str] = []

    def for_services(self, names: Iterable[str]) -> "SystemdService":
        self._names = list(names)
        return self

    def get_status(self) -> ServicesReport:
        states = [
            ServiceState(
                name=name,
                present=self._systemctl.exists(name),
                enabled=self._systemctl.is_enabled(name),
                active=self._systemctl.is_active(name),
            )
            for name in self._names
        ]
        return ServicesReport(services=states)
```

- [ ] **Step 4: Run to verify pass.**

---

## Task 7: DockerService

**Files:**
- Create: `src/fonfon/services/docker_service.py`
- Test: `tests/test_docker_service.py`

Behavior: if docker is unavailable, `docker_installed=False` and the rest is empty/false. Otherwise inspect the named container: `present` from inspect, `listening[port]` true when the container publishes that host port, `external_network` true when attached to a non-default network (anything other than `bridge`/`host`/`none`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docker_service.py
from fonfon.services.docker_service import DockerService


class FakeDocker:
    def __init__(self, available=True, inspect=None):
        self._available, self._inspect = available, inspect
    def is_available(self): return self._available
    def inspect_container(self, name): return self._inspect


def test_docker_absent_marks_not_installed():
    report = (DockerService(docker=FakeDocker(available=False))
              .for_service("traefik").ensure_listening(host="0.0.0.0", ports=[80, 443]))
    assert report.docker_installed is False
    assert report.present is False


def test_traefik_listening_and_external_network():
    inspect = {
        "Name": "/traefik",
        "NetworkSettings": {
            "Ports": {
                "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}],
                "443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "443"}],
            },
            "Networks": {"web": {}},
        },
    }
    report = (DockerService(docker=FakeDocker(inspect=inspect))
              .for_service("traefik").ensure_listening(host="0.0.0.0", ports=[80, 443]))
    assert report.docker_installed is True
    assert report.present is True
    assert report.listening == {80: True, 443: True}
    assert report.external_network is True


def test_traefik_absent_when_inspect_none():
    report = (DockerService(docker=FakeDocker(inspect=None))
              .for_service("traefik").ensure_listening(host="0.0.0.0", ports=[80]))
    assert report.present is False
    assert report.listening == {80: False}
    assert report.external_network is False
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

```python
# src/fonfon/services/docker_service.py
from pydantic import BaseModel
from fonfon.system.docker_cli import DockerCli

_DEFAULT_NETWORKS = {"bridge", "host", "none"}


class DockerReport(BaseModel):
    docker_installed: bool
    service: str | None = None
    present: bool = False
    host: str | None = None
    listening: dict[int, bool] = {}
    external_network: bool = False


class DockerService:
    def __init__(self, docker: DockerCli | None = None):
        self._docker = docker or DockerCli()
        self._service: str | None = None

    def for_service(self, name: str) -> "DockerService":
        self._service = name
        return self

    def ensure_listening(self, host: str, ports: list[int]) -> DockerReport:
        if not self._docker.is_available():
            return DockerReport(docker_installed=False, service=self._service,
                                host=host, listening={p: False for p in ports})
        inspect = self._docker.inspect_container(self._service)
        if inspect is None:
            return DockerReport(docker_installed=True, service=self._service, present=False,
                                host=host, listening={p: False for p in ports},
                                external_network=False)
        net = inspect.get("NetworkSettings", {})
        published = net.get("Ports") or {}
        listening = {
            port: any(b.get("HostPort") == str(port)
                      for b in (published.get(f"{port}/tcp") or []))
            for port in ports
        }
        networks = set(net.get("Networks", {}).keys())
        return DockerReport(
            docker_installed=True, service=self._service, present=True, host=host,
            listening=listening, external_network=bool(networks - _DEFAULT_NETWORKS),
        )
```

- [ ] **Step 4: Run to verify pass.**

---

## Task 8: `check` use-case + policy mapping

**Files:**
- Create: `src/fonfon/services/check.py`
- Test: `tests/test_check.py`

`build_report(...)` is pure (takes domain DTOs, returns `CheckReport`) so the policy matrix is fully unit-testable. `run_check()` wires the real services and selects the package backend from the detected distro.

- [ ] **Step 1: Write failing tests** (policy matrix + unsupported-distro SKIP)

```python
# tests/test_check.py
from fonfon.models import CheckStatus
from fonfon.services.check import build_report
from fonfon.services.os_service import OSInfo
from fonfon.services.package_service import PackageReport
from fonfon.services.systemd_service import ServicesReport, ServiceState
from fonfon.services.network_service import NetworkInfo
from fonfon.services.docker_service import DockerReport
from fonfon.system.dpkg import PackageState


def _items(report, title):
    section = next(s for s in report.sections if s.title == title)
    return {i.label: i for i in section.items}


def _base(**over):
    args = dict(
        os_info=OSInfo(distro="Debian 12", distro_id="debian", architecture="x86_64"),
        packages=PackageReport(packages=[
            PackageState(name="sudo", installed=True, version="1.9"),
            PackageState(name="docker-ce", installed=False, version=None),
        ]),
        services=ServicesReport(services=[
            ServiceState(name="ssh", present=True, enabled=True, active=True),
            ServiceState(name="docker", present=False, enabled=False, active=False),
        ]),
        network=NetworkInfo(interfaces={"eth0": "203.0.113.5"}, public_ip="203.0.113.5"),
        docker=DockerReport(docker_installed=False),
    )
    args.update(over)
    return build_report(**args)


def test_system_items_are_info():
    report = _base()
    assert _items(report, "System")["Architecture"].status is CheckStatus.INFO


def test_installed_package_ok_missing_fail():
    pkgs = _items(_base(), "Packages")
    assert pkgs["sudo"].status is CheckStatus.OK
    assert pkgs["docker-ce"].status is CheckStatus.FAIL


def test_enabled_service_ok_disabled_fail():
    svcs = _items(_base(), "Services")
    assert svcs["ssh"].status is CheckStatus.OK
    assert svcs["docker"].status is CheckStatus.FAIL


def test_network_items_are_info():
    net = _items(_base(), "Network")
    assert all(i.status is CheckStatus.INFO for i in net.values())


def test_docker_absent_section_is_skip():
    dock = _items(_base(), "Docker")
    assert all(i.status is CheckStatus.SKIP for i in dock.values())


def test_docker_gaps_are_warn():
    report = _base(docker=DockerReport(
        docker_installed=True, service="traefik", present=False,
        listening={80: False, 443: False}, external_network=False))
    dock = _items(report, "Docker")
    assert all(i.status is CheckStatus.WARN for i in dock.values())


def test_unsupported_distro_packages_section_is_skip():
    report = _base(packages=None)
    pkgs = _items(report, "Packages")
    assert all(i.status is CheckStatus.SKIP for i in pkgs.values())


def test_report_ok_false_when_fail_present():
    assert _base().ok is False
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `check.py`**

```python
# src/fonfon/services/check.py
"""The `check` use-case: compose domain services and apply status policy."""

from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus
from fonfon.services.docker_service import DockerReport, DockerService
from fonfon.services.network_service import NetworkInfo, NetworkService
from fonfon.services.os_service import OSInfo, OSService
from fonfon.services.package_backends import UnsupportedDistroError, select_package_backend
from fonfon.services.package_service import PackageReport, PackageService
from fonfon.services.systemd_service import ServicesReport, SystemdService

PACKAGES = ["sudo", "docker-ce", "tailscale", "python3-pipx"]
SERVICES = ["docker", "ssh", "tailscaled"]
TRAEFIK_PORTS = [80, 443]


def run_check() -> CheckReport:
    os_info = OSService().get_info()
    services = SystemdService().for_services(SERVICES).get_status()
    network = NetworkService().get_ips()
    docker = (DockerService().for_service("traefik")
              .ensure_listening(host="0.0.0.0", ports=TRAEFIK_PORTS))
    try:
        backend = select_package_backend(os_info.distro_id)
        packages: PackageReport | None = (
            PackageService(backend).for_packages(PACKAGES).ensure_installed())
    except UnsupportedDistroError:
        packages = None
    return build_report(os_info, packages, services, network, docker)


def build_report(os_info: OSInfo, packages: PackageReport | None,
                 services: ServicesReport, network: NetworkInfo,
                 docker: DockerReport) -> CheckReport:
    return CheckReport(sections=[
        _system_section(os_info),
        _packages_section(os_info, packages),
        _services_section(services),
        _network_section(network),
        _docker_section(docker),
    ])


def _system_section(os_info: OSInfo) -> CheckSection:
    return CheckSection(title="System", items=[
        CheckItem(key="system.distro", label="Distro",
                  status=CheckStatus.INFO, detail=os_info.distro),
        CheckItem(key="system.arch", label="Architecture",
                  status=CheckStatus.INFO, detail=os_info.architecture),
    ])


def _packages_section(os_info: OSInfo, packages: PackageReport | None) -> CheckSection:
    if packages is None:
        return CheckSection(title="Packages", items=[
            CheckItem(key="package.unsupported", label="packages",
                      status=CheckStatus.SKIP,
                      detail=f"package checks unsupported on {os_info.distro_id}")])
    items = [
        CheckItem(
            key=f"package.{p.name}", label=p.name,
            status=CheckStatus.OK if p.installed else CheckStatus.FAIL,
            detail=p.version if p.installed else "not installed",
        )
        for p in packages.packages
    ]
    return CheckSection(title="Packages", items=items)


def _services_section(services: ServicesReport) -> CheckSection:
    items = []
    for s in services.services:
        if s.enabled:
            detail = "enabled, active" if s.active else "enabled, inactive"
        elif not s.present:
            detail = "not found"
        else:
            detail = "not enabled"
        items.append(CheckItem(
            key=f"service.{s.name}", label=s.name,
            status=CheckStatus.OK if s.enabled else CheckStatus.FAIL, detail=detail))
    return CheckSection(title="Services", items=items)


def _network_section(network: NetworkInfo) -> CheckSection:
    items = [
        CheckItem(key=f"network.{name}", label=name, status=CheckStatus.INFO, detail=ip)
        for name, ip in network.interfaces.items()
    ]
    items.append(CheckItem(key="network.public", label="public", status=CheckStatus.INFO,
                           detail=network.public_ip or "unknown"))
    return CheckSection(title="Network", items=items)


def _docker_section(docker: DockerReport) -> CheckSection:
    if not docker.docker_installed:
        return CheckSection(title="Docker", items=[
            CheckItem(key="docker.skip", label="docker", status=CheckStatus.SKIP,
                      detail="docker not installed")])
    name = docker.service or "service"
    present = CheckItem(
        key="docker.traefik", label=name,
        status=CheckStatus.OK if docker.present else CheckStatus.WARN,
        detail="running" if docker.present else "container not running")
    ports = CheckItem(
        key="docker.ports", label="ports 80/443",
        status=CheckStatus.OK if all(docker.listening.values()) and docker.listening
        else CheckStatus.WARN,
        detail="listening" if all(docker.listening.values()) and docker.listening
        else "not listening")
    network = CheckItem(
        key="docker.network", label="ext. network",
        status=CheckStatus.OK if docker.external_network else CheckStatus.WARN,
        detail="attached" if docker.external_network else "none attached")
    return CheckSection(title="Docker", items=[present, ports, network])
```

- [ ] **Step 4: Run to verify pass.**

---

## Task 9: ui header + output renderers

**Files:**
- Modify: `src/fonfon/ui.py` (add `build_header`)
- Create: `src/fonfon/output/__init__.py` (empty)
- Create: `src/fonfon/output/console.py`
- Create: `src/fonfon/output/json.py`
- Test: `tests/test_output.py` (extend existing `tests/test_ui.py` for the header if preferred)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_output.py
import json as json_module
from io import StringIO
from rich.console import Console
from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus
from fonfon.output import console as console_renderer
from fonfon.output import json as json_renderer


def _report():
    return CheckReport(sections=[CheckSection(title="Packages", items=[
        CheckItem(key="package.sudo", label="sudo", status=CheckStatus.OK, detail="1.9"),
        CheckItem(key="package.docker-ce", label="docker-ce", status=CheckStatus.FAIL,
                  detail="not installed"),
    ])])


def _render(renderer):
    buffer = StringIO()
    renderer.render(_report(), Console(file=buffer, force_terminal=False, width=100))
    return buffer.getvalue()


def test_console_render_includes_labels_and_section():
    out = _render(console_renderer)
    assert "Packages" in out
    assert "sudo" in out and "docker-ce" in out


def test_json_render_is_valid_and_roundtrips():
    out = _render(json_renderer)
    data = json_module.loads(out)
    assert data["sections"][0]["items"][0]["status"] == "ok"
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement header + renderers**

```python
# add to src/fonfon/ui.py
from rich.table import Table
from fonfon.logo import CAT_LOGO, ORANGE, ORANGE_BRIGHT


def build_header(version: str) -> RenderableType:
    """Two-column header: the cat logo beside 'fonfon - vX.Y.Z'."""
    grid = Table.grid(padding=(0, 4))
    grid.add_column()
    grid.add_column(vertical="middle")
    grid.add_row(Text(CAT_LOGO, style=ORANGE),
                 Text(f"fonfon - v{version}", style=f"bold {ORANGE_BRIGHT}"))
    return grid
```

```python
# src/fonfon/output/console.py
from rich.console import Console
from rich.table import Table
from fonfon import get_version
from fonfon.logo import ORANGE_BRIGHT
from fonfon.models import CheckReport, CheckStatus
from fonfon.ui import build_header

_STYLE = {
    CheckStatus.OK: ("green", "✓ OK"),
    CheckStatus.WARN: ("yellow", "! WARN"),
    CheckStatus.FAIL: ("red", "✗ FAIL"),
    CheckStatus.INFO: ("cyan", "• INFO"),
    CheckStatus.SKIP: ("dim", "– SKIP"),
}


def render(report: CheckReport, console: Console) -> None:
    console.print(build_header(get_version()))
    table = Table(show_header=True, header_style=f"bold {ORANGE_BRIGHT}", expand=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for section in report.sections:
        table.add_section()
        table.add_row(f"[bold]{section.title}[/bold]", "", "")
        for item in section.items:
            style, label = _STYLE[item.status]
            table.add_row(f"  {item.label}", f"[{style}]{label}[/{style}]", item.detail or "")
    console.print(table)
    fails = sum(1 for s in report.sections for i in s.items if i.status is CheckStatus.FAIL)
    warns = sum(1 for s in report.sections for i in s.items if i.status is CheckStatus.WARN)
    if report.ok:
        console.print(f"[green]✓ all checks passed[/green] · {warns} warnings")
    else:
        console.print(f"[red]✗ {fails} failed[/red] · {warns} warnings — checks did not pass")
```

```python
# src/fonfon/output/json.py
from rich.console import Console
from fonfon.models import CheckReport


def render(report: CheckReport, console: Console) -> None:
    # rich emits plain (parseable) JSON when not attached to a terminal
    console.print_json(report.model_dump_json())
```

- [ ] **Step 4: Run to verify pass.** Also run `uv run pytest tests/test_ui.py -v` to confirm the existing banner test still passes.

---

## Task 10: CLI `check` command + `--output`

**Files:**
- Modify: `src/fonfon/cli.py`
- Test: `tests/test_cli_check.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_check.py
import json as json_module
from click.testing import CliRunner
from fonfon.cli import main
from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus


def _patch_report(monkeypatch, *statuses):
    items = [CheckItem(key=f"k{i}", label=f"L{i}", status=s, detail="d")
             for i, s in enumerate(statuses)]
    report = CheckReport(sections=[CheckSection(title="S", items=items)])
    monkeypatch.setattr("fonfon.cli.run_check", lambda: report)


def test_check_exits_zero_when_all_ok(monkeypatch):
    _patch_report(monkeypatch, CheckStatus.OK, CheckStatus.INFO)
    result = CliRunner().invoke(main, ["check"])
    assert result.exit_code == 0


def test_check_exits_one_on_failure(monkeypatch):
    _patch_report(monkeypatch, CheckStatus.FAIL)
    result = CliRunner().invoke(main, ["check"])
    assert result.exit_code == 1


def test_check_json_output_parses(monkeypatch):
    _patch_report(monkeypatch, CheckStatus.OK)
    result = CliRunner().invoke(main, ["check", "--output", "json"])
    data = json_module.loads(result.output)
    assert data["sections"][0]["items"][0]["status"] == "ok"
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement the `check` command**

Add to `src/fonfon/cli.py` (keep the existing group + banner intact):

```python
from fonfon.output import console as console_renderer
from fonfon.output import json as json_renderer
from fonfon.services.check import run_check


@main.command()
@click.option("-o", "--output", "output_format",
              type=click.Choice(["console", "json"]), default="console",
              help="Output format.")
@click.pass_context
def check(ctx: click.Context, output_format: str) -> None:
    """Report whether this system is ready to serve applications."""
    report = run_check()
    console = Console()
    if output_format == "json":
        json_renderer.render(report, console)
    else:
        console_renderer.render(report, console)
    ctx.exit(0 if report.ok else 1)
```

- [ ] **Step 4: Run to verify pass.** Then run the full suite: `uv run pytest -v` (all unit tests green).

---

## Task 11: documentation + CLAUDE.md architecture

**Files:**
- Create: `docs/manual/docs/commands/check.md`
- Modify: `docs/manual/mkdocs.yml` (nav entry)
- Modify: `CLAUDE.md` (add Architecture section)

- [ ] **Step 1: Write the manual page** `docs/manual/docs/commands/check.md`

````markdown
# `fonfon check`

`fonfon check` reports whether a server is ready to serve applications. It is
**read-only** — it inspects the system and prints a report; it changes nothing.

## Usage

```bash
fonfon check                # rich, colored table (default)
fonfon check --output json  # machine-readable JSON
```

## What it checks

| Area | Items |
|------|-------|
| System | distro, architecture |
| Packages | `sudo`, `docker-ce`, `tailscale`, `python3-pipx` |
| Services | `docker`, `ssh`, `tailscaled` (systemd enabled/active) |
| Network | per-interface IPv4 + best-effort public IP |
| Docker | traefik running, listening on 80/443, attached to an external network |

## Exit code

`check` exits non-zero if any item fails (a missing package or a disabled
service). Warnings (e.g. traefik not yet configured) and informational items do
not affect the exit code, so `fonfon check` works as a provisioning gate.

> Package detection currently supports Debian-family distros (dpkg). On other
> distros the Packages section is skipped.
````

- [ ] **Step 2: Add nav entry** in `docs/manual/mkdocs.yml` under `nav:` (create the key if absent):

```yaml
nav:
  - Home: index.md
  - Getting Started: getting-started.md
  - Commands:
      - check: commands/check.md
```
(Adjust to match the existing nav structure already in the file.)

- [ ] **Step 3: Build the docs to verify** `uv run mkdocs build --strict -f docs/manual/mkdocs.yml`
Expected: builds with no warnings (strict).

- [ ] **Step 4: Add an Architecture section to `CLAUDE.md`** (after the existing "Architecture" paragraph, extend it):

```markdown
### Layered design

Commands flow through four layers:

1. **Input** — `cli.py` (click): parses args, picks an output format.
2. **Domain services** — `services/*_service.py`: fluent, reusable probes for one
   area each (`OSService`, `PackageService`, `SystemdService`, `NetworkService`,
   `DockerService`). They return plain-fact DTOs and contain no policy.
3. **Use-case** — e.g. `services/check.py::run_check`: composes services and
   applies status policy, producing a `CheckReport` (`models.py`).
4. **Output** — `output/console.py` and `output/json.py`: render `CheckReport`.

All OS interaction lives in `system/` boundary adapters (`Systemctl`, `Dpkg`,
`DockerCli`, `probes`), injected into services so everything is unit-testable
without a real server. Package detection uses a Strategy keyed on distro
(`services/package_backends.py`); only Debian/dpkg ships today.

Runtime deps: click, rich, pydantic.
```

- [ ] **Step 5:** No automated test; verify `mkdocs build --strict` passed in Step 3.

---

## Task 12: integration smoke for `check`

**Files:**
- Modify: `tests/integration/test_smoke.py` (add a `check` assertion)

- [ ] **Step 1: Add a failing-by-default integration test** (runs only with `--run-integration` on a Lima VM; mirrors the existing version smoke test, reusing its `vm_run` fixture and `FONFON_TEST_SCIE`).

```python
# append to tests/integration/test_smoke.py
import os
import pytest


@pytest.mark.integration
def test_check_runs_on_real_debian(vm_run):
    scie = os.environ["FONFON_TEST_SCIE"]
    result = vm_run(f"sudo {scie} check --output json")
    # check may exit non-zero (unprovisioned box); we assert it ran and emitted JSON
    assert '"sections"' in result.stdout
```
(Match the existing fixture/env names in `tests/integration/conftest.py`; adjust `vm_run`/`FONFON_TEST_SCIE` if they differ.)

- [ ] **Step 2:** Confirm it is deselected by default: `uv run pytest tests/integration -v` → skipped/deselected without `--run-integration`. Do not boot a VM here.

---

## Final verification (after all tasks)

- [ ] `uv run pytest -v` — full unit suite green, output pristine.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` — clean (or run `pre-commit run --all-files`).
- [ ] `uv run mkdocs build --strict -f docs/manual/mkdocs.yml` — docs build.
- [ ] Manual smoke on the dev host: `uv run fonfon check` renders the table; `uv run fonfon check --output json | python -m json.tool` parses. (On macOS the Packages/Services sections will reflect the absence of `dpkg`/`systemctl` — expected; the Debian VM is the real target.)
- [ ] Leave everything **uncommitted** for the maintainer to review and commit.

## Self-review notes (author)

- **Spec coverage:** every spec section maps to a task — DTOs (T1), adapters (T2–T3), the five services (T4–T7), policy + exit code (T8), renderers + header + mockup (T9), CLI + `--output` (T10), docs/manual + CLAUDE.md (T11), integration (T12). pydantic→runtime dep (T1).
- **Type consistency:** `PackageState` defined once in `system/dpkg.py`, imported by `package_backends`, `package_service`, and `check` tests. `OSInfo`/`NetworkInfo`/`ServicesReport`/`DockerReport`/`PackageReport` names match across producer and `build_report` consumer. Renderer status map covers all five `CheckStatus` members.
- **No placeholders:** all code/test steps are concrete.
