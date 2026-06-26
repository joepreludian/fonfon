# Traefik posture in `fonfon check` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the **Docker** section of `fonfon check` to report Traefik posture as four items: container running, the named `traefik` network created, ports 80/443 published, and the dashboard (port 8080) listening **only** on the host's tailnet IP — failing the check if the dashboard is exposed publicly.

**Architecture:** Existing `check` layering — `DockerCli` (boundary, unchanged) → `DockerService` (facts, no policy) → `check.run_check`/`build_report` (status policy) → `output/` (rendering, unchanged). No new adapter or runtime dependency.

**Tech Stack:** Python 3.14, click, rich, pydantic. Tests: pytest. Docs: mkdocs-material.

## Global Constraints

- The network item checks the **named** `traefik` network via `DockerCli.network_exists` (`docker network inspect traefik`), not a container-attachment heuristic.
- "Dashboard tailnet-only" = there is ≥1 `8080/tcp` binding **and** every binding's `HostIp` equals the host's tailnet IP (read from the `tailscale0` interface).
- "Dashboard public" = any `8080/tcp` binding's `HostIp` is in `{"0.0.0.0", "::", ""}`. A public dashboard is **`FAIL`**; not-running / not-published / unknown-tailnet-IP is `WARN`.
- The tailnet IP comes from the `Network` section's `tailscale0` interface (already gathered in `run_check`); no Tailscale-adapter call is added.
- Run `uv run pytest` and let the pre-commit git hook run on every commit. Use conventional-commit messages. Do NOT add "Co-authored-by".
- The final task bumps `pyproject.toml` by one **minor** (new feature) over whatever it currently reads.

---

### Task 1: `DockerService` — network + dashboard facts

**Files:**
- Modify: `src/fonfon/services/docker_service.py`
- Test: `tests/test_docker_service.py`

**Interfaces:**
- Consumes: `DockerCli.is_available` / `inspect_container` / `network_exists` (existing).
- Produces: `DockerReport` gains `network_name: str | None`, `network_present: bool`, `dashboard_port: int | None`, `dashboard_tailnet_only: bool`, `dashboard_public: bool`, `tailnet_ip: str | None`; `DockerService.ensure_listening(host, ports, *, network=None, dashboard_port=None, tailnet_ip=None)` computes them. (`external_network` is kept for now — removed in Task 3 — so `check.py` stays green.)

- [ ] **Step 1: Write the failing tests** in `tests/test_docker_service.py`

Extend `FakeDocker` in place to support the named-network check (backward compatible — `networks` defaults empty, so existing tests that pass no `network` are unaffected):

```python
class FakeDocker:
    def __init__(self, available=True, inspect=None, networks=()):
        self._available, self._inspect = available, inspect
        self._networks = set(networks)

    def is_available(self):
        return self._available

    def inspect_container(self, name):
        return self._inspect

    def network_exists(self, name):
        return name in self._networks
```

Append the new tests:

```python
def test_network_present_true_when_named_network_exists():
    inspect = {"NetworkSettings": {"Ports": {}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect, networks=["traefik"]))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], network="traefik")
    )
    assert report.network_present is True
    assert report.network_name == "traefik"


def test_network_present_false_when_absent():
    inspect = {"NetworkSettings": {"Ports": {}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], network="traefik")
    )
    assert report.network_present is False


def test_network_checked_even_when_container_absent():
    report = (
        DockerService(docker=FakeDocker(inspect=None, networks=["traefik"]))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [80], network="traefik")
    )
    assert report.present is False
    assert report.network_present is True


def test_dashboard_tailnet_only_when_bound_to_tailnet_ip():
    inspect = {"NetworkSettings": {"Ports": {
        "8080/tcp": [{"HostIp": "100.64.0.1", "HostPort": "8080"}]}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip="100.64.0.1")
    )
    assert report.dashboard_tailnet_only is True
    assert report.dashboard_public is False


def test_dashboard_public_when_bound_to_all_interfaces():
    inspect = {"NetworkSettings": {"Ports": {
        "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip="100.64.0.1")
    )
    assert report.dashboard_public is True
    assert report.dashboard_tailnet_only is False


def test_dashboard_not_tailnet_only_when_tailnet_ip_unknown():
    inspect = {"NetworkSettings": {"Ports": {
        "8080/tcp": [{"HostIp": "100.64.0.1", "HostPort": "8080"}]}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip=None)
    )
    assert report.dashboard_tailnet_only is False
    assert report.dashboard_public is False


def test_dashboard_unpublished_gives_both_false():
    inspect = {"NetworkSettings": {"Ports": {}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip="100.64.0.1")
    )
    assert report.dashboard_public is False
    assert report.dashboard_tailnet_only is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_docker_service.py -v`
Expected: FAIL — `TypeError: ensure_listening() got an unexpected keyword argument 'network'` (and the new fields don't exist).

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/services/docker_service.py`

Add the new fields to `DockerReport` (keep `external_network` for now):

```python
class DockerReport(BaseModel):
    docker_installed: bool
    service: str | None = None
    present: bool = False
    host: str | None = None
    listening: dict[int, bool] = Field(default_factory=dict)
    external_network: bool = False
    network_name: str | None = None
    network_present: bool = False
    dashboard_port: int | None = None
    dashboard_tailnet_only: bool = False
    dashboard_public: bool = False
    tailnet_ip: str | None = None
```

Replace `ensure_listening` with the keyword-extended version (keeps the existing `external_network` computation, adds the network/dashboard facts, and checks the network even when the container is absent):

```python
    def ensure_listening(
        self,
        host: str,
        ports: list[int],
        *,
        network: str | None = None,
        dashboard_port: int | None = None,
        tailnet_ip: str | None = None,
    ) -> DockerReport:
        if not self._docker.is_available():
            return DockerReport(
                docker_installed=False,
                service=self._service,
                host=host,
                listening={p: False for p in ports},
                network_name=network,
                dashboard_port=dashboard_port,
                tailnet_ip=tailnet_ip,
            )
        network_present = self._docker.network_exists(network) if network else False
        inspect = self._docker.inspect_container(self._service)
        if inspect is None:
            return DockerReport(
                docker_installed=True,
                service=self._service,
                present=False,
                host=host,
                listening={p: False for p in ports},
                external_network=False,
                network_name=network,
                network_present=network_present,
                dashboard_port=dashboard_port,
                tailnet_ip=tailnet_ip,
            )
        net = inspect.get("NetworkSettings", {})
        published = net.get("Ports") or {}
        listening = {
            port: any(
                b.get("HostPort") == str(port)
                and b.get("HostIp") in (host, "0.0.0.0")
                for b in (published.get(f"{port}/tcp") or [])
            )
            for port in ports
        }
        dashboard_public = False
        dashboard_tailnet_only = False
        if dashboard_port is not None:
            binds = published.get(f"{dashboard_port}/tcp") or []
            host_ips = [b.get("HostIp") for b in binds]
            dashboard_public = any(ip in {"0.0.0.0", "::", ""} for ip in host_ips)
            dashboard_tailnet_only = (
                bool(binds)
                and tailnet_ip is not None
                and all(ip == tailnet_ip for ip in host_ips)
            )
        networks = set(net.get("Networks", {}).keys())
        return DockerReport(
            docker_installed=True,
            service=self._service,
            present=True,
            host=host,
            listening=listening,
            external_network=bool(networks - _DEFAULT_NETWORKS),
            network_name=network,
            network_present=network_present,
            dashboard_port=dashboard_port,
            dashboard_public=dashboard_public,
            dashboard_tailnet_only=dashboard_tailnet_only,
            tailnet_ip=tailnet_ip,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_docker_service.py -v`
Expected: PASS (the pre-existing `external_network`/`listening` tests still pass)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/docker_service.py tests/test_docker_service.py
git commit -m "feat: gather traefik network + dashboard-binding facts in DockerService"
```

---

### Task 2: `check` Docker section — four items + tailnet IP wiring

**Files:**
- Modify: `src/fonfon/services/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: the new `DockerReport` facts (Task 1); `TRAEFIK_NETWORK` (from `services/traefik_config.py`).
- Produces: a four-item Docker `CheckSection` (`docker.traefik`, `docker.network`, `docker.ports`, `docker.dashboard`); `run_check` passes `network`, `dashboard_port`, and the `tailscale0` IP into `ensure_listening`.

- [ ] **Step 1: Write/adjust the failing tests** in `tests/test_check.py`

Replace `test_docker_gaps_are_warn` and `test_docker_all_ok_path` (they reference `external_network` and assume three items) and add dashboard/network coverage:

```python
def test_docker_gaps_are_warn():
    report = _base(
        docker=DockerReport(
            docker_installed=True,
            service="traefik",
            present=False,
            listening={80: False, 443: False},
            network_present=False,
            network_name="traefik",
            dashboard_port=8080,
            tailnet_ip=None,
        )
    )
    dock = _items(report, "Docker")
    assert all(i.status is CheckStatus.WARN for i in dock.values())


def test_docker_all_ok_path():
    docker = DockerReport(
        docker_installed=True,
        service="traefik",
        present=True,
        listening={80: True, 443: True},
        network_present=True,
        network_name="traefik",
        dashboard_port=8080,
        dashboard_tailnet_only=True,
        tailnet_ip="100.64.0.1",
    )
    items = _items(_base(docker=docker), "Docker")
    assert all(i.status is CheckStatus.OK for i in items.values())


def test_docker_dashboard_public_is_fail():
    docker = DockerReport(
        docker_installed=True,
        service="traefik",
        present=True,
        listening={80: True, 443: True},
        network_present=True,
        network_name="traefik",
        dashboard_port=8080,
        dashboard_public=True,
        tailnet_ip="100.64.0.1",
    )
    item = _items(_base(docker=docker), "Docker")["dashboard (tailnet-only)"]
    assert item.status is CheckStatus.FAIL
    assert "publicly" in item.detail


def test_docker_dashboard_tailnet_only_is_ok_with_ip_detail():
    docker = DockerReport(
        docker_installed=True,
        service="traefik",
        present=True,
        listening={80: True, 443: True},
        network_present=True,
        network_name="traefik",
        dashboard_port=8080,
        dashboard_tailnet_only=True,
        tailnet_ip="100.64.0.1",
    )
    item = _items(_base(docker=docker), "Docker")["dashboard (tailnet-only)"]
    assert item.status is CheckStatus.OK
    assert "100.64.0.1" in item.detail


def test_docker_network_created_ok_missing_warn():
    common = dict(
        docker_installed=True,
        service="traefik",
        present=True,
        listening={80: True, 443: True},
        network_name="traefik",
        dashboard_port=8080,
        dashboard_tailnet_only=True,
        tailnet_ip="100.64.0.1",
    )
    created = DockerReport(network_present=True, **common)
    missing = DockerReport(network_present=False, **common)
    assert _items(_base(docker=created), "Docker")["network"].status is CheckStatus.OK
    assert _items(_base(docker=missing), "Docker")["network"].status is CheckStatus.WARN
```

(The `test_docker_absent_section_is_skip` test is unchanged — a non-installed Docker still yields a SKIP section.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_check.py -v`
Expected: FAIL — `KeyError: 'dashboard (tailnet-only)'` / `KeyError: 'network'` (the section still emits the old three items and reads `external_network`).

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/services/check.py`

Add imports/constants near the top:

```python
from fonfon.services.traefik_config import TRAEFIK_NETWORK

PACKAGES = ["sudo", "docker-ce", "tailscale", "pipx"]
SERVICES = ["docker", "ssh", "tailscaled", "sdci"]
TRAEFIK_PORTS = [80, 443]
TRAEFIK_DASHBOARD_PORT = 8080
TAILSCALE_IFACE = "tailscale0"
```

Wire `run_check` to derive the tailnet IP and pass the new args:

```python
    network = NetworkService().get_ips()
    tailnet_ip = network.interfaces.get(TAILSCALE_IFACE)
    docker = (
        DockerService()
        .for_service("traefik")
        .ensure_listening(
            host="0.0.0.0",
            ports=TRAEFIK_PORTS,
            network=TRAEFIK_NETWORK,
            dashboard_port=TRAEFIK_DASHBOARD_PORT,
            tailnet_ip=tailnet_ip,
        )
    )
```

Replace `_docker_section` with the four-item version + the dashboard helper:

```python
def _docker_section(docker: DockerReport) -> CheckSection:
    if not docker.docker_installed:
        return CheckSection(
            title="Docker",
            items=[
                CheckItem(
                    key="docker.skip",
                    label="docker",
                    status=CheckStatus.SKIP,
                    detail="docker not installed",
                )
            ],
        )
    name = docker.service or "service"
    present = CheckItem(
        key="docker.traefik",
        label=name,
        status=CheckStatus.OK if docker.present else CheckStatus.WARN,
        detail="running" if docker.present else "container not running",
    )
    net_name = docker.network_name or "external"
    network = CheckItem(
        key="docker.network",
        label="network",
        status=CheckStatus.OK if docker.network_present else CheckStatus.WARN,
        detail=(
            f"'{net_name}' created"
            if docker.network_present
            else f"'{net_name}' not created"
        ),
    )
    listening_ok = bool(docker.listening) and all(docker.listening.values())
    ports = CheckItem(
        key="docker.ports",
        label="ports 80/443",
        status=CheckStatus.OK if listening_ok else CheckStatus.WARN,
        detail="listening" if listening_ok else "not listening",
    )
    return CheckSection(
        title="Docker", items=[present, network, ports, _dashboard_item(docker)]
    )


def _dashboard_item(docker: DockerReport) -> CheckItem:
    port = docker.dashboard_port
    if not docker.present:
        status, detail = CheckStatus.WARN, "container not running"
    elif docker.dashboard_public:
        status, detail = CheckStatus.FAIL, f"exposed publicly (0.0.0.0:{port})"
    elif docker.dashboard_tailnet_only:
        status, detail = CheckStatus.OK, f"tailnet-only ({docker.tailnet_ip}:{port})"
    elif docker.tailnet_ip is None:
        status, detail = CheckStatus.WARN, "tailnet IP unknown (is tailscale up?)"
    else:
        status, detail = CheckStatus.WARN, "not published on tailnet"
    return CheckItem(
        key="docker.dashboard",
        label="dashboard (tailnet-only)",
        status=status,
        detail=detail,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_check.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/check.py tests/test_check.py
git commit -m "feat: report traefik network + tailnet-only dashboard in fonfon check"
```

---

### Task 3: Remove the dead `external_network` fact

**Files:**
- Modify: `src/fonfon/services/docker_service.py`
- Test: `tests/test_docker_service.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `DockerReport` without `external_network`; `DockerService` without the `_DEFAULT_NETWORKS` heuristic (now superseded by the named-network check).

- [ ] **Step 1: Update the tests** in `tests/test_docker_service.py`

- Delete `test_only_default_networks_gives_external_network_false`.
- In `test_traefik_listening_and_external_network`: rename to `test_traefik_listening` and drop the `assert report.external_network is True` line (keep the `listening` assertions).
- In `test_traefik_absent_when_inspect_none`: drop the `assert report.external_network is False` line.

- [ ] **Step 2: Write the implementation** in `src/fonfon/services/docker_service.py`

- Remove the `external_network: bool = False` field from `DockerReport`.
- Remove the module-level `_DEFAULT_NETWORKS = {...}` constant.
- Remove `external_network=...` from both `DockerReport(...)` returns in `ensure_listening`, and delete the now-unused `networks = set(net.get("Networks", {}).keys())` line.

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/test_docker_service.py tests/test_check.py -v`
Expected: PASS (nothing references `external_network` anymore)

- [ ] **Step 4: Commit**

```bash
git add src/fonfon/services/docker_service.py tests/test_docker_service.py
git commit -m "refactor: drop superseded external_network heuristic from DockerReport"
```

---

### Task 4: Documentation + version bump

**Files:**
- Modify: `docs/manual/docs/commands/check.md`
- Modify: `pyproject.toml`
- Regenerate: `docs/manual/site/`

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: an updated Docker row + dashboard note; the next minor version.

- [ ] **Step 1: Run the full suite to confirm a green baseline**

Run: `uv run pytest`
Expected: PASS (Tasks 1–3).

- [ ] **Step 2: Update the check command page**

In `docs/manual/docs/commands/check.md`, replace the Docker row of the "What it checks" table:

```markdown
| Docker | traefik container running; the external `traefik` network created; ports 80/443 published; the dashboard (8080) listening **only** on the tailnet |
```

Add a note under the table (or near the exit-code section):

```markdown
!!! warning "Traefik dashboard must stay on the tailnet"
    The Docker section's **dashboard (tailnet-only)** item is `OK` only when
    Traefik's port 8080 is bound to this host's Tailscale IP. If it is bound to a
    public address (`0.0.0.0`), the item is **`FAIL`** and `fonfon check` exits
    non-zero — a publicly reachable dashboard defeats the tailnet-only model. A
    box without Traefik running reports the Docker items as `WARN`, not `FAIL`.
```

Update the existing "Warnings (e.g. traefik not yet configured) ... do not affect the exit code" sentence to note the one exception: a publicly-exposed dashboard fails.

- [ ] **Step 3: Bump the version**

In `pyproject.toml`, bump the `version` by one minor (new feature) over whatever it currently reads (e.g. `0.6.0` → `0.7.0`).

- [ ] **Step 4: Rebuild the committed docs site**

Run: `uv run mkdocs build -f docs/manual/mkdocs.yml`
Expected: builds into `docs/manual/site/` with no errors.

- [ ] **Step 5: Commit**

```bash
git add docs/manual/docs/commands/check.md docs/manual/site pyproject.toml
git commit -m "docs: document traefik posture in fonfon check; bump version"
```

---

## Final verification

- [ ] **Run the full unit suite:** `uv run pytest` → all green.
- [ ] **Run the linters/hooks:** `uv run pre-commit run --all-files` → all pass.
- [ ] **Sanity-check the output shape:** construct a `CheckReport` (or run on a VM) and confirm the Docker section lists four rows: `traefik`, `network`, `ports 80/443`, `dashboard (tailnet-only)`.
- [ ] **Optional end-to-end:** on a Debian VM with Traefik deployed (`make debian-demo` with a tailscale key + `--traefik-cert-email`), run `sudo fonfon check` and confirm the dashboard row is `OK tailnet-only (100.x:8080)`; then temporarily republish 8080 on `0.0.0.0` and confirm the row flips to `FAIL` and the exit code is non-zero.

## Self-review notes (author)

- **Spec coverage:** container presence (existing `present` item), named `traefik` network created (Tasks 1/2 `network_present`), ports 80/443 (existing `listening`), dashboard tailnet-only with FAIL-on-public (Tasks 1/2 `dashboard_*`), tailnet IP from `tailscale0` (Task 2 wiring), docs + version (Task 4) — all mapped.
- **Green-between-tasks:** Task 1 keeps `external_network` so `check._docker_section` (which still reads it) stays valid; Task 2 switches the policy off it; Task 3 removes the now-dead field and its tests. Each task leaves `uv run pytest` green.
- **`run_check` is not unit-tested directly** (tests exercise `build_report`), so the new wiring is covered via the policy tests plus the optional VM check.
- **Detail strings** include the concrete IP/port (`tailnet-only (100.64.0.1:8080)`, `exposed publicly (0.0.0.0:8080)`) so the report is actionable.
