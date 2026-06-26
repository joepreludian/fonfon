# Traefik service setup step — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three `SetupStep`s to `fonfon setup` that provision Traefik as a Docker-Compose reverse proxy — dashboard bound to the tailnet, public :80/:443 entrypoints, an external `traefik` network, opt-in routing via labels, and Let's Encrypt HTTP-01 certificates — gated on a new `--traefik-cert-email` flag.

**Architecture:** Follows the existing `setup` layering: small single-purpose `SetupStep`s (`is_satisfied()` probe + `apply()` mutation), all OS interaction behind injectable boundary adapters in `system/`, pure config rendering in `services/traefik_config.py`, presentation DTOs in `models_setup.py`, rendering in `output/`. Traefik steps run inside the existing `if auth_key:` branch of `build_steps`, additionally gated on `cert_email`.

**Tech Stack:** Python 3.14, click, rich, pydantic. Tests: pytest. Docs: mkdocs-material. No new runtime dependencies (YAML is hand-rendered as strings — `pyyaml` is not a dependency).

## Global Constraints

- Traefik image is pinned to exactly `traefik:v3.7.5`.
- External Docker network name is exactly `traefik`.
- Certificate resolver name is exactly `le` (Let's Encrypt, HTTP-01 challenge on the `web` entrypoint).
- `providers.docker.exposedByDefault` MUST be `false`.
- Dashboard is published on the host only at `<tailnet_ip>:8080:8080` (tailnet-only); `:80` and `:443` publish on all interfaces.
- The cert-email flag is `--traefik-cert-email`, env var `FONFON_TRAEFIK_CERT_EMAIL`.
- The Tailscale flag is `--tailscale-key`, env var `FONFON_TAILSCALE_KEY` (the codebase is mid-rename from `--tailscale-auth-key`; this plan completes that rename across code, tests, and docs).
- Service directories are mode `0700`; generated config files are mode `0644`; all owned by the operator user.
- Run `uv run pytest` and let the pre-commit git hook run on every commit. Use conventional-commit messages. Do NOT add "Co-authored-by".
- The final task bumps `pyproject.toml` `version` from `0.4.1` to `0.5.0` (one minor bump for the whole feature).

---

### Task 1: `traefik_paths` helper

**Files:**
- Create: `src/fonfon/services/traefik_paths.py`
- Test: `tests/test_traefik_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TraefikPaths` (pydantic `BaseModel` with str fields `base`, `acme`, `dynamic`, `compose_file`, `static_config`); `traefik_paths(user: str) -> TraefikPaths`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_traefik_paths.py
from fonfon.services.traefik_paths import traefik_paths


def test_traefik_paths_under_user_home():
    paths = traefik_paths("deploy")
    assert paths.base == "/home/deploy/services/traefik"
    assert paths.acme == "/home/deploy/services/traefik/acme"
    assert paths.dynamic == "/home/deploy/services/traefik/dynamic"
    assert paths.compose_file == "/home/deploy/services/traefik/docker-compose.yml"
    assert paths.static_config == "/home/deploy/services/traefik/traefik.yml"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_traefik_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fonfon.services.traefik_paths'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fonfon/services/traefik_paths.py
"""Derive the operator's Traefik service-directory paths from a username."""

from pydantic import BaseModel


class TraefikPaths(BaseModel):
    """Paths for the Traefik service-directory tree under a user's home."""

    base: str
    acme: str
    dynamic: str
    compose_file: str
    static_config: str


def traefik_paths(user: str) -> TraefikPaths:
    """Return the Traefik service-dir tree for `user` under their home directory."""
    base = f"/home/{user}/services/traefik"
    return TraefikPaths(
        base=base,
        acme=f"{base}/acme",
        dynamic=f"{base}/dynamic",
        compose_file=f"{base}/docker-compose.yml",
        static_config=f"{base}/traefik.yml",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_traefik_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/traefik_paths.py tests/test_traefik_paths.py
git commit -m "feat: add traefik_paths service-directory helper"
```

---

### Task 2: `Fs.write_file`

**Files:**
- Modify: `src/fonfon/system/fs.py`
- Test: `tests/test_fs.py`

**Interfaces:**
- Consumes: the existing `Fs.__init__(run, exists)` signature.
- Produces: `Fs.__init__(run, exists, write_text=None)` (new optional injected writer, default `lambda p, c: pathlib.Path(p).write_text(c)`); `Fs.write_file(path: str, content: str, owner: str, mode: str) -> None` — writes content, then `chown owner:owner path` and `chmod mode path` via the runner; raises `RuntimeError` on chown/chmod failure.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_fs.py`)

```python
def test_write_file_writes_content_and_sets_owner_and_mode():
    written = {}
    calls = []

    def fake_write_text(path, content):
        written[path] = content

    def run(args, timeout=10, env=None):
        calls.append(args)
        return completed(args, 0, "")

    fs = Fs(run=run, write_text=fake_write_text)
    fs.write_file("/srv/traefik/traefik.yml", "api: {}\n", "deploy", "0644")

    assert written["/srv/traefik/traefik.yml"] == "api: {}\n"
    assert ["chown", "deploy:deploy", "/srv/traefik/traefik.yml"] in calls
    assert ["chmod", "0644", "/srv/traefik/traefik.yml"] in calls


def test_write_file_raises_when_chown_fails():
    def run(args, timeout=10, env=None):
        if args[0] == "chown":
            return completed(args, 1, "", "boom")
        return completed(args, 0, "")

    fs = Fs(run=run, write_text=lambda p, c: None)
    with pytest.raises(RuntimeError, match="chown"):
        fs.write_file("/x", "c", "deploy", "0644")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fs.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'write_text'`

- [ ] **Step 3: Write minimal implementation** (replace the body of `src/fonfon/system/fs.py`)

```python
"""Boundary adapter for filesystem directory creation and file writes."""

import os
import pathlib
from collections.abc import Callable

from fonfon.system._run import run as _default_run


def _default_write_text(path: str, content: str) -> None:
    pathlib.Path(path).write_text(content)


class Fs:
    def __init__(
        self,
        run: Callable = _default_run,
        exists: Callable[[str], bool] = os.path.exists,
        write_text: Callable[[str, str], None] = _default_write_text,
    ):
        self._run = run
        self._exists = exists
        self._write_text = write_text

    def exists(self, path: str) -> bool:
        return self._exists(path)

    def make_dir(self, path: str, owner: str, mode: str) -> None:
        proc = self._run(["install", "-d", "-o", owner, "-g", owner, "-m", mode, path])
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"install -d {path} failed (rc {proc.returncode}): {detail}"
            )

    def write_file(self, path: str, content: str, owner: str, mode: str) -> None:
        self._write_text(path, content)
        chown = self._run(["chown", f"{owner}:{owner}", path])
        if chown.returncode != 0:
            detail = chown.stderr.strip() or chown.stdout.strip()
            raise RuntimeError(
                f"chown {path} failed (rc {chown.returncode}): {detail}"
            )
        chmod = self._run(["chmod", mode, path])
        if chmod.returncode != 0:
            detail = chmod.stderr.strip() or chmod.stdout.strip()
            raise RuntimeError(
                f"chmod {path} failed (rc {chmod.returncode}): {detail}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fs.py -v`
Expected: PASS (all 5 tests, including the 3 pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/system/fs.py tests/test_fs.py
git commit -m "feat: add Fs.write_file for owner/mode-controlled file writes"
```

---

### Task 3: `DockerCli` network methods

**Files:**
- Modify: `src/fonfon/system/docker_cli.py`
- Test: `tests/test_docker_cli.py`

**Interfaces:**
- Consumes: the existing `DockerCli(run)` adapter; its runner is called as `self._run([...])` (no timeout/env kwargs).
- Produces: `DockerCli.network_exists(name: str) -> bool` (true iff `docker network inspect <name>` exits 0); `DockerCli.create_network(name: str) -> None` (runs `docker network create <name>`, raises `RuntimeError` on non-zero).

- [ ] **Step 1: Write the failing tests** in `tests/test_docker_cli.py`

First add `import pytest` to the top of the file (above the existing
`from fonfon.system.docker_cli import DockerCli` line) so it stays at module top
(avoids ruff `E402`). Then append the test functions:

```python
def test_network_exists_true_on_zero_exit():
    docker = DockerCli(run=lambda args, timeout=10: completed(args, 0, "[]"))
    assert docker.network_exists("traefik") is True


def test_network_exists_false_on_nonzero_exit():
    docker = DockerCli(
        run=lambda args, timeout=10: completed(args, 1, "", "No such network")
    )
    assert docker.network_exists("traefik") is False


def test_create_network_runs_docker_network_create():
    seen = {}

    def run(args, timeout=10):
        seen["args"] = args
        return completed(args, 0, "abc123")

    DockerCli(run=run).create_network("traefik")
    assert seen["args"] == ["docker", "network", "create", "traefik"]


def test_create_network_raises_on_failure():
    docker = DockerCli(run=lambda args, timeout=10: completed(args, 1, "", "boom"))
    with pytest.raises(RuntimeError, match="boom"):
        docker.create_network("traefik")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_docker_cli.py -v`
Expected: FAIL — `AttributeError: 'DockerCli' object has no attribute 'network_exists'`

- [ ] **Step 3: Write minimal implementation** (append these methods to the `DockerCli` class in `src/fonfon/system/docker_cli.py`)

```python
    def network_exists(self, name: str) -> bool:
        return self._run(["docker", "network", "inspect", name]).returncode == 0

    def create_network(self, name: str) -> None:
        proc = self._run(["docker", "network", "create", name])
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"docker network create {name} failed "
                f"(rc {proc.returncode}): {detail}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_docker_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/system/docker_cli.py tests/test_docker_cli.py
git commit -m "feat: add docker network inspect/create to DockerCli"
```

---

### Task 4: `DockerCompose` adapter

**Files:**
- Create: `src/fonfon/system/docker_compose.py`
- Test: `tests/test_docker_compose.py`

**Interfaces:**
- Consumes: `fonfon.system._run.run` (the default runner; signature `(args, timeout=10, env=None)`).
- Produces: `DockerCompose(run=_default_run)`; `DockerCompose.up(compose_file: str) -> None` — runs `docker compose -f <compose_file> up -d` with a 600s timeout, raises `RuntimeError` on non-zero.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_docker_compose.py
import pytest

from fonfon.system.docker_compose import DockerCompose
from tests.fakes import completed


def test_up_runs_docker_compose_up_detached():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    DockerCompose(run=run).up("/srv/traefik/docker-compose.yml")
    assert seen["args"] == [
        "docker",
        "compose",
        "-f",
        "/srv/traefik/docker-compose.yml",
        "up",
        "-d",
    ]
    assert seen["timeout"] >= 600


def test_up_raises_on_failure():
    def run(args, timeout=10, env=None):
        return completed(args, 1, "", "compose error")

    with pytest.raises(RuntimeError, match="compose error"):
        DockerCompose(run=run).up("/srv/traefik/docker-compose.yml")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_docker_compose.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.system.docker_compose'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fonfon/system/docker_compose.py
"""Boundary adapter for docker compose: bring a stack up."""

from collections.abc import Callable

from fonfon.system._run import run as _default_run

DOCKER_COMPOSE_TIMEOUT = 600  # image pulls + container start can be slow


class DockerCompose:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def up(self, compose_file: str) -> None:
        proc = self._run(
            ["docker", "compose", "-f", compose_file, "up", "-d"],
            timeout=DOCKER_COMPOSE_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"docker compose up failed (rc {proc.returncode}): {detail}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_docker_compose.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/system/docker_compose.py tests/test_docker_compose.py
git commit -m "feat: add DockerCompose adapter with up"
```

---

### Task 5: `TraefikDeployment` model + widen the deployment union

**Files:**
- Modify: `src/fonfon/models_setup.py`
- Test: `tests/test_models_setup.py`

**Interfaces:**
- Consumes: the existing `SdciDeployment`, `StepResult` models.
- Produces: `TraefikDeployment` (pydantic `BaseModel` with str fields `compose_file`, `network`, `dashboard_url`, `cert_email`); `StepResult.deployment: SdciDeployment | TraefikDeployment | None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_models_setup.py`

First, add `TraefikDeployment` to the existing top-of-file import so it stays at module top (avoids ruff `E402`):

```python
from fonfon.models_setup import (
    SdciDeployment,
    SetupReport,
    SetupStatus,
    StepResult,
    TraefikDeployment,
)
```

Then append the two test functions (no mid-file imports — `StepResult`/`SetupStatus` are already imported above):

```python
def test_traefik_deployment_fields():
    dep = TraefikDeployment(
        compose_file="/home/deploy/services/traefik/docker-compose.yml",
        network="traefik",
        dashboard_url="http://100.64.0.1:8080/dashboard/",
        cert_email="you@example.com",
    )
    assert dep.network == "traefik"
    assert dep.dashboard_url == "http://100.64.0.1:8080/dashboard/"


def test_step_result_accepts_traefik_deployment():
    dep = TraefikDeployment(
        compose_file="c",
        network="traefik",
        dashboard_url="u",
        cert_email="e",
    )
    result = StepResult(title="Traefik", status=SetupStatus.INSTALLED, deployment=dep)
    assert isinstance(result.deployment, TraefikDeployment)
    assert result.deployment.network == "traefik"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models_setup.py -v`
Expected: FAIL — `ImportError: cannot import name 'TraefikDeployment'`

- [ ] **Step 3: Write minimal implementation** — add the model and widen the field in `src/fonfon/models_setup.py`

Add after the `SdciDeployment` class:

```python
class TraefikDeployment(BaseModel):
    compose_file: str
    network: str
    dashboard_url: str
    cert_email: str
```

Change `StepResult.deployment` from:

```python
    deployment: SdciDeployment | None = None
```

to:

```python
    deployment: SdciDeployment | TraefikDeployment | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_setup.py tests/test_setup_output.py -v`
Expected: PASS (the existing sdci-deployment serialization tests must still pass — the union keeps the concrete type)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/models_setup.py tests/test_models_setup.py
git commit -m "feat: add TraefikDeployment DTO and widen StepResult.deployment"
```

---

### Task 6: Traefik config renderers

**Files:**
- Create: `src/fonfon/services/traefik_config.py`
- Test: `tests/test_traefik_config.py`

**Interfaces:**
- Consumes: `TraefikPaths` (from Task 1).
- Produces: constants `TRAEFIK_IMAGE = "traefik:v3.7.5"`, `TRAEFIK_NETWORK = "traefik"`; `render_static_config(cert_email: str) -> str`; `render_compose(tailnet_ip: str, paths: TraefikPaths) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_traefik_config.py
from fonfon.services.traefik_config import (
    TRAEFIK_IMAGE,
    TRAEFIK_NETWORK,
    render_compose,
    render_static_config,
)
from fonfon.services.traefik_paths import traefik_paths


def test_static_config_disables_expose_by_default_and_sets_resolver():
    out = render_static_config("you@example.com")
    assert "exposedByDefault: false" in out
    assert "email: you@example.com" in out
    assert "httpChallenge:" in out
    assert "entryPoint: web" in out
    assert "storage: /acme/acme.json" in out
    assert f"network: {TRAEFIK_NETWORK}" in out
    assert "insecure: true" in out


def test_static_config_redirects_web_to_websecure():
    out = render_static_config("you@example.com")
    assert 'address: ":80"' in out
    assert 'address: ":443"' in out
    assert "to: websecure" in out
    assert "scheme: https" in out


def test_compose_pins_image_and_binds_dashboard_to_tailnet():
    paths = traefik_paths("deploy")
    out = render_compose("100.64.0.1", paths)
    assert f"image: {TRAEFIK_IMAGE}" in out
    assert TRAEFIK_IMAGE == "traefik:v3.7.5"
    assert '"100.64.0.1:8080:8080"' in out
    assert '"80:80"' in out
    assert '"443:443"' in out


def test_compose_mounts_config_and_uses_external_network():
    paths = traefik_paths("deploy")
    out = render_compose("100.64.0.1", paths)
    assert f"{paths.static_config}:/etc/traefik/traefik.yml:ro" in out
    assert f"{paths.dynamic}:/etc/traefik/dynamic:ro" in out
    assert f"{paths.acme}:/acme" in out
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in out
    assert "external: true" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_traefik_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.services.traefik_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fonfon/services/traefik_config.py
"""Pure renderers for Traefik's static config and docker-compose file.

YAML is emitted as plain strings to avoid a pyyaml runtime dependency.
"""

from fonfon.services.traefik_paths import TraefikPaths

TRAEFIK_IMAGE = "traefik:v3.7.5"
TRAEFIK_NETWORK = "traefik"


def render_static_config(cert_email: str) -> str:
    """Return Traefik's static `traefik.yml`.

    Entrypoints: web (:80, redirects to websecure + serves the ACME HTTP-01
    challenge) and websecure (:443). The Docker provider does not expose
    containers unless they opt in with labels. The dashboard is served on the
    `traefik` API (:8080); host-side port binding keeps it tailnet-only.
    """
    return f"""\
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

api:
  dashboard: true
  insecure: true

providers:
  docker:
    exposedByDefault: false
    network: {TRAEFIK_NETWORK}
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  le:
    acme:
      email: {cert_email}
      storage: /acme/acme.json
      httpChallenge:
        entryPoint: web
"""


def render_compose(tailnet_ip: str, paths: TraefikPaths) -> str:
    """Return the Traefik `docker-compose.yml`.

    Publishes :80 and :443 on all interfaces and the dashboard (:8080) only on
    the host's tailnet IP, mounts the docker socket read-only plus the generated
    config, and joins the external `traefik` network.
    """
    return f"""\
services:
  traefik:
    image: {TRAEFIK_IMAGE}
    container_name: traefik
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "{tailnet_ip}:8080:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - {paths.static_config}:/etc/traefik/traefik.yml:ro
      - {paths.dynamic}:/etc/traefik/dynamic:ro
      - {paths.acme}:/acme
    networks:
      - {TRAEFIK_NETWORK}

networks:
  {TRAEFIK_NETWORK}:
    external: true
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_traefik_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/traefik_config.py tests/test_traefik_config.py
git commit -m "feat: add Traefik static-config and compose renderers"
```

---

### Task 7: Traefik setup steps

**Files:**
- Modify: `src/fonfon/services/setup_steps.py`
- Test: `tests/test_setup_steps.py`

**Interfaces:**
- Consumes: `TraefikPaths`, `traefik_paths` (Task 1); `Fs.write_file` (Task 2); `DockerCli.network_exists`/`create_network`/`inspect_container` (Task 3); `DockerCompose.up` (Task 4); `TraefikDeployment` (Task 5); `TRAEFIK_NETWORK`, `render_compose`, `render_static_config` (Task 6); `Tailscale.ipv4` (existing).
- Produces:
  - `TraefikDirsStep(user: str, paths: TraefikPaths, fs: Fs | None = None)` — title `"Traefik dirs"`.
  - `TraefikNetworkStep(docker: DockerCli | None = None)` — title `"Traefik network"`.
  - `TraefikStep(user: str, paths: TraefikPaths, cert_email: str, tailscale=None, docker=None, compose=None, fs=None)` — title `"Traefik"`; on apply sets `self.deployment: TraefikDeployment`.
  - Constants `TRAEFIK_DIR_MODE = "0700"`, `TRAEFIK_FILE_MODE = "0644"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_setup_steps.py`

First, extend the imports at the **top** of the file (keep them at module top to
avoid ruff `E402`). Add `TraefikDirsStep`, `TraefikNetworkStep`, `TraefikStep` to
the existing `from fonfon.services.setup_steps import (...)` block, and add two
new import lines beneath it:

```python
from fonfon.services.traefik_config import TRAEFIK_IMAGE, TRAEFIK_NETWORK
from fonfon.services.traefik_paths import traefik_paths
```

Then **modify the existing `FakeFs` class in place** (do not redefine it — that
trips ruff `F811`). Add a `writes` list and a `write_file` method to the class
already defined near the bottom of the file:

```python
class FakeFs:
    def __init__(self, existing=()):
        self._existing = set(existing)
        self.made = []
        self.writes = []

    def exists(self, path):
        return path in self._existing

    def make_dir(self, path, owner, mode):
        self.made.append((path, owner, mode))
        self._existing.add(path)

    def write_file(self, path, content, owner, mode):
        self.writes.append((path, content, owner, mode))
        self._existing.add(path)
```

Finally, append the new fakes and tests to the end of the file (no mid-file
imports; `FakeTailscale` is already defined in this file from the sdci tests):

```python
# ── Traefik steps ──────────────────────────────────────────────────────────────


class FakeDockerCli:
    def __init__(self, networks=(), container=None):
        self._networks = set(networks)
        self._container = container
        self.created = []

    def network_exists(self, name):
        return name in self._networks

    def create_network(self, name):
        self.created.append(name)
        self._networks.add(name)

    def inspect_container(self, name):
        return self._container


class FakeCompose:
    def __init__(self):
        self.upped = []

    def up(self, compose_file):
        self.upped.append(compose_file)


TPATHS = traefik_paths("deploy")


def test_traefik_dirs_satisfied_when_all_exist():
    fs = FakeFs(existing=(TPATHS.base, TPATHS.acme, TPATHS.dynamic))
    assert TraefikDirsStep("deploy", TPATHS, fs=fs).is_satisfied() is True


def test_traefik_dirs_not_satisfied_when_any_missing():
    fs = FakeFs(existing=(TPATHS.base, TPATHS.acme))
    assert TraefikDirsStep("deploy", TPATHS, fs=fs).is_satisfied() is False


def test_traefik_dirs_apply_creates_base_acme_dynamic_0700():
    fs = FakeFs()
    TraefikDirsStep("deploy", TPATHS, fs=fs).apply()
    assert fs.made == [
        (TPATHS.base, "deploy", "0700"),
        (TPATHS.acme, "deploy", "0700"),
        (TPATHS.dynamic, "deploy", "0700"),
    ]


def test_traefik_network_satisfied_when_exists():
    docker = FakeDockerCli(networks=[TRAEFIK_NETWORK])
    assert TraefikNetworkStep(docker=docker).is_satisfied() is True


def test_traefik_network_not_satisfied_when_absent():
    assert TraefikNetworkStep(docker=FakeDockerCli()).is_satisfied() is False


def test_traefik_network_apply_creates_network():
    docker = FakeDockerCli()
    TraefikNetworkStep(docker=docker).apply()
    assert docker.created == [TRAEFIK_NETWORK]


def test_traefik_satisfied_when_container_running():
    docker = FakeDockerCli(container={"State": {"Running": True}})
    step = TraefikStep("deploy", TPATHS, "you@example.com", docker=docker)
    assert step.is_satisfied() is True


def test_traefik_not_satisfied_when_container_absent_or_stopped():
    assert (
        TraefikStep(
            "deploy", TPATHS, "you@example.com", docker=FakeDockerCli(container=None)
        ).is_satisfied()
        is False
    )
    stopped = FakeDockerCli(container={"State": {"Running": False}})
    assert (
        TraefikStep("deploy", TPATHS, "you@example.com", docker=stopped).is_satisfied()
        is False
    )


def test_traefik_apply_writes_files_brings_up_and_sets_deployment():
    fs = FakeFs()
    docker = FakeDockerCli()
    compose = FakeCompose()
    ts = FakeTailscale(ip="100.64.0.1")
    step = TraefikStep(
        "deploy",
        TPATHS,
        "you@example.com",
        tailscale=ts,
        docker=docker,
        compose=compose,
        fs=fs,
    )
    step.apply()

    # static config written to traefik.yml, compose to docker-compose.yml, 0644
    written = {path: (content, owner, mode) for path, content, owner, mode in fs.writes}
    assert TPATHS.static_config in written
    assert TPATHS.compose_file in written
    assert written[TPATHS.static_config][1:] == ("deploy", "0644")
    assert written[TPATHS.compose_file][1:] == ("deploy", "0644")
    # compose content pins the image and binds the dashboard to the tailnet IP
    assert TRAEFIK_IMAGE in written[TPATHS.compose_file][0]
    assert "100.64.0.1:8080:8080" in written[TPATHS.compose_file][0]
    # static config disables expose-by-default and carries the cert email
    assert "exposedByDefault: false" in written[TPATHS.static_config][0]
    assert "you@example.com" in written[TPATHS.static_config][0]
    # stack brought up
    assert compose.upped == [TPATHS.compose_file]
    # deployment surfaced
    assert step.deployment.network == TRAEFIK_NETWORK
    assert step.deployment.compose_file == TPATHS.compose_file
    assert step.deployment.dashboard_url == "http://100.64.0.1:8080/dashboard/"
    assert step.deployment.cert_email == "you@example.com"


def test_traefik_apply_raises_without_ip():
    step = TraefikStep(
        "deploy",
        TPATHS,
        "you@example.com",
        tailscale=FakeTailscale(ip=None),
        docker=FakeDockerCli(),
        compose=FakeCompose(),
        fs=FakeFs(),
    )
    with pytest.raises(RuntimeError):
        step.apply()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup_steps.py -v`
Expected: FAIL — `ImportError: cannot import name 'TraefikDirsStep' from 'fonfon.services.setup_steps'`

- [ ] **Step 3: Write minimal implementation** — in `src/fonfon/services/setup_steps.py`

Add to the imports at the top of the file:

```python
from fonfon.models_setup import SdciDeployment, TraefikDeployment
from fonfon.services.traefik_config import (
    TRAEFIK_NETWORK,
    render_compose,
    render_static_config,
)
from fonfon.services.traefik_paths import TraefikPaths
from fonfon.system.docker_cli import DockerCli
from fonfon.system.docker_compose import DockerCompose
```

(The existing `from fonfon.models_setup import SdciDeployment` line is replaced by the combined import above.)

Widen the base-class attribute annotation:

```python
class SetupStep(ABC):
    """Base class for an idempotent provisioning action."""

    title: str
    deployment: SdciDeployment | TraefikDeployment | None = None
```

Add the Traefik constants near the other module constants:

```python
TRAEFIK_DIR_MODE = "0700"
TRAEFIK_FILE_MODE = "0644"
```

Append the three step classes to the end of the file:

```python
class TraefikDirsStep(SetupStep):
    """Create the operator's Traefik service directories (base, acme, dynamic)."""

    title = "Traefik dirs"

    def __init__(self, user: str, paths: TraefikPaths, fs: Fs | None = None) -> None:
        self._user = user
        self._paths = paths
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        return (
            self._fs.exists(self._paths.base)
            and self._fs.exists(self._paths.acme)
            and self._fs.exists(self._paths.dynamic)
        )

    def apply(self) -> None:
        for path in (self._paths.base, self._paths.acme, self._paths.dynamic):
            self._fs.make_dir(path, self._user, TRAEFIK_DIR_MODE)


class TraefikNetworkStep(SetupStep):
    """Create the external `traefik` Docker network."""

    title = "Traefik network"

    def __init__(self, docker: DockerCli | None = None) -> None:
        self._docker = docker or DockerCli()

    def is_satisfied(self) -> bool:
        return self._docker.network_exists(TRAEFIK_NETWORK)

    def apply(self) -> None:
        self._docker.create_network(TRAEFIK_NETWORK)


class TraefikStep(SetupStep):
    """Write Traefik's config + compose file and bring the stack up."""

    title = "Traefik"

    def __init__(
        self,
        user: str,
        paths: TraefikPaths,
        cert_email: str,
        tailscale: Tailscale | None = None,
        docker: DockerCli | None = None,
        compose: DockerCompose | None = None,
        fs: Fs | None = None,
    ) -> None:
        self._user = user
        self._paths = paths
        self._cert_email = cert_email
        self._tailscale = tailscale or Tailscale()
        self._docker = docker or DockerCli()
        self._compose = compose or DockerCompose()
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        inspect = self._docker.inspect_container("traefik")
        return bool(inspect and inspect.get("State", {}).get("Running"))

    def apply(self) -> None:
        ip = self._tailscale.ipv4()
        if ip is None:
            raise RuntimeError(
                "no Tailscale IPv4 available; is `tailscale up` complete?"
            )
        self._fs.write_file(
            self._paths.static_config,
            render_static_config(self._cert_email),
            self._user,
            TRAEFIK_FILE_MODE,
        )
        self._fs.write_file(
            self._paths.compose_file,
            render_compose(ip, self._paths),
            self._user,
            TRAEFIK_FILE_MODE,
        )
        self._compose.up(self._paths.compose_file)
        self.deployment = TraefikDeployment(
            compose_file=self._paths.compose_file,
            network=TRAEFIK_NETWORK,
            dashboard_url=f"http://{ip}:8080/dashboard/",
            cert_email=self._cert_email,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup_steps.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/setup_steps.py tests/test_setup_steps.py
git commit -m "feat: add Traefik dirs, network, and deploy setup steps"
```

---

### Task 8: Wire Traefik steps into `build_steps` / `run_setup`

**Files:**
- Modify: `src/fonfon/services/setup.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `TraefikDirsStep`, `TraefikNetworkStep`, `TraefikStep` (Task 7); `traefik_paths` (Task 1); `DockerCli` (Task 3); `DockerCompose` (Task 4); `Fs`, `Tailscale` (existing).
- Produces: `build_steps(new_user: str, auth_key: str | None = None, cert_email: str | None = None, run=_default_run) -> list[SetupStep]` — appends the three Traefik steps after the sdci steps, only when `auth_key` and `cert_email` are both truthy; `run_setup(new_user, auth_key=None, cert_email=None, *, run=..., on_step_start=None, on_result=None) -> SetupReport`.

- [ ] **Step 1: Write/adjust the failing tests** in `tests/test_setup.py`

Update the three `monkeypatch.setattr("fonfon.services.setup.build_steps", ...)` lambdas — change each `lambda u, k=None, run=None: steps` to:

```python
        "fonfon.services.setup.build_steps", lambda u, k=None, c=None, run=None: steps
```

(There are three occurrences — in `test_run_setup_calls_on_result_per_step`, `test_run_setup_calls_on_step_start_per_step`, and `test_run_setup_on_step_start_called_before_on_result`.)

Then append the new coverage:

```python
def test_build_steps_with_auth_key_and_cert_email_appends_traefik_steps():
    titles = [s.title for s in build_steps("jon", "tskey-abc", "you@example.com")]
    assert titles == [
        "User",
        "Docker",
        "Docker group",
        "Tailscale",
        "pipx",
        "sdci",
        "Tailscale up",
        "sdci dirs",
        "sdci config",
        "Traefik dirs",
        "Traefik network",
        "Traefik",
    ]


def test_build_steps_with_auth_key_but_no_cert_email_skips_traefik():
    titles = [s.title for s in build_steps("jon", "tskey-abc")]
    assert "Traefik" not in titles
    assert titles[-1] == "sdci config"


def test_build_steps_cert_email_without_auth_key_adds_nothing():
    # Traefik needs the tailnet IP, so without an auth key it must not appear.
    titles = [s.title for s in build_steps("jon", None, "you@example.com")]
    assert titles == ["User", "Docker", "Docker group", "Tailscale", "pipx", "sdci"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -v`
Expected: FAIL — `TypeError: build_steps() takes ... positional arguments but 3 were given`

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/services/setup.py`

Add imports:

```python
from fonfon.services.setup_steps import (
    DockerGroupStep,
    DockerStep,
    PipxStep,
    SdciConfigStep,
    SdciDirsStep,
    SdciStep,
    SetupStep,
    TailscaleStep,
    TailscaleUpStep,
    TraefikDirsStep,
    TraefikNetworkStep,
    TraefikStep,
    UserStep,
)
from fonfon.services.traefik_paths import traefik_paths
from fonfon.system.docker_cli import DockerCli
from fonfon.system.docker_compose import DockerCompose
```

Change `build_steps` signature and add the Traefik block inside `if auth_key:`:

```python
def build_steps(
    new_user: str,
    auth_key: str | None = None,
    cert_email: str | None = None,
    run: Callable = _default_run,
) -> list[SetupStep]:
    """Return the provisioning steps in execution order.

    The sdci service-configuration steps are appended only when an auth key is
    supplied. The Traefik steps are appended only when both an auth key (needed
    for the tailnet IP) and a cert email are supplied.
    """
    steps: list[SetupStep] = [
        UserStep(new_user, users=Users(run=run)),
        DockerStep(apt=Apt(run=run), dpkg=Dpkg(run=run), run=run),
        DockerGroupStep(new_user, users=Users(run=run)),
        TailscaleStep(dpkg=Dpkg(run=run), run=run),
        PipxStep(apt=Apt(run=run), dpkg=Dpkg(run=run)),
        SdciStep(pipx=Pipx(run=run)),
    ]
    if auth_key:
        paths = sdci_paths(new_user)
        steps.append(TailscaleUpStep(auth_key, tailscale=Tailscale(run=run)))
        steps.append(SdciDirsStep(new_user, paths, fs=Fs(run=run)))
        steps.append(
            SdciConfigStep(
                new_user,
                paths,
                tailscale=Tailscale(run=run),
                sdci=Sdci(run=run),
            )
        )
        if cert_email:
            tpaths = traefik_paths(new_user)
            steps.append(TraefikDirsStep(new_user, tpaths, fs=Fs(run=run)))
            steps.append(TraefikNetworkStep(docker=DockerCli(run=run)))
            steps.append(
                TraefikStep(
                    new_user,
                    tpaths,
                    cert_email,
                    tailscale=Tailscale(run=run),
                    docker=DockerCli(run=run),
                    compose=DockerCompose(run=run),
                    fs=Fs(run=run),
                )
            )
    return steps
```

Change `run_setup` to accept and thread `cert_email`:

```python
def run_setup(
    new_user: str,
    auth_key: str | None = None,
    cert_email: str | None = None,
    *,
    run: Callable = _default_run,
    on_step_start: Callable[[SetupStep], None] | None = None,
    on_result: Callable[[StepResult], None] | None = None,
) -> SetupReport:
    """Run all provisioning steps and return the aggregated report."""
    results = []
    for step in build_steps(new_user, auth_key, cert_email, run=run):
        if on_step_start is not None:
            on_step_start(step)
        result = run_step(step)
        if on_result is not None:
            on_result(result)
        results.append(result)
    return SetupReport(steps=results)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/setup.py tests/test_setup.py
git commit -m "feat: wire Traefik steps into build_steps behind cert email"
```

---

### Task 9: CLI flag `--traefik-cert-email` + finish the `--tailscale-key` rename

**Files:**
- Modify: `src/fonfon/cli.py`
- Test: `tests/test_cli_setup.py`

**Interfaces:**
- Consumes: `run_setup(new_user, auth_key, cert_email, *, run, on_step_start, on_result)` (Task 8).
- Produces: `setup` command with options `--tailscale-key` (env `FONFON_TAILSCALE_KEY`, param `tailscale_key`) and `--traefik-cert-email` (env `FONFON_TRAEFIK_CERT_EMAIL`, param `traefik_cert_email`); both passed positionally to `run_setup`.

- [ ] **Step 1: Update the failing tests** in `tests/test_cli_setup.py`

Replace the key constant and the `_patch_run_setup` helper, and the env-var names, so the suite uses the new flag and the cert-email-aware `run_setup` signature:

```python
_KEY = ["--tailscale-key", "tskey-test"]


def _patch_run_setup(monkeypatch, report):
    monkeypatch.setattr(
        "fonfon.cli.run_setup",
        lambda u, k, c=None, run=None, on_step_start=None, on_result=None: report,
    )
```

In `test_setup_requires_auth_key`, change the env key:

```python
    result = CliRunner().invoke(
        main, ["setup", "jon"], env={"FONFON_TAILSCALE_KEY": ""}
    )
```

In `test_setup_accepts_key_from_env`, change the env key:

```python
    result = CliRunner().invoke(
        main, ["setup", "jon"], env={"FONFON_TAILSCALE_KEY": "tskey-env"}
    )
```

Add a test that the cert-email flag reaches `run_setup`:

```python
def test_setup_passes_cert_email_to_run_setup(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    seen = {}

    def _spy(u, k, c=None, run=None, on_step_start=None, on_result=None):
        seen["user"], seen["key"], seen["cert_email"] = u, k, c
        return _ok_report()

    monkeypatch.setattr("fonfon.cli.run_setup", _spy)
    result = CliRunner().invoke(
        main,
        ["setup", "jon", *_KEY, "--traefik-cert-email", "you@example.com"],
    )
    assert result.exit_code == 0
    assert seen["cert_email"] == "you@example.com"


def test_setup_cert_email_from_env(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    seen = {}

    def _spy(u, k, c=None, run=None, on_step_start=None, on_result=None):
        seen["cert_email"] = c
        return _ok_report()

    monkeypatch.setattr("fonfon.cli.run_setup", _spy)
    result = CliRunner().invoke(
        main,
        ["setup", "jon", *_KEY],
        env={"FONFON_TRAEFIK_CERT_EMAIL": "env@example.com"},
    )
    assert result.exit_code == 0
    assert seen["cert_email"] == "env@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: FAIL — the `setup()` callback currently declares `tailscale_auth_key` (so click binding fails) and has no `--traefik-cert-email` option.

- [ ] **Step 3: Write minimal implementation** — replace the `setup` command in `src/fonfon/cli.py`

```python
@main.command()
@click.argument("new_user")
@click.option(
    "--tailscale-key",
    "tailscale_key",
    envvar="FONFON_TAILSCALE_KEY",
    default=None,
    help="Tailscale auth key to join the tailnet (or set FONFON_TAILSCALE_KEY).",
)
@click.option(
    "--traefik-cert-email",
    "traefik_cert_email",
    envvar="FONFON_TRAEFIK_CERT_EMAIL",
    default=None,
    help=(
        "Let's Encrypt email for Traefik certificates "
        "(or set FONFON_TRAEFIK_CERT_EMAIL). Provisions Traefik when set."
    ),
)
@click.option(
    "-o",
    "--output",
    "output_format",
    type=click.Choice(["console", "json"]),
    default="console",
    help="Output format.",
)
@click.pass_context
def setup(
    ctx: click.Context,
    new_user: str,
    tailscale_key: str | None,
    traefik_cert_email: str | None,
    output_format: str,
) -> None:
    """Provision this server (Docker, Tailscale, pipx, sdci), join the tailnet,
    configure sdci-server, and (with --traefik-cert-email) deploy Traefik."""
    console = Console()
    if os.geteuid() != 0:
        console.print("[red]fonfon setup must be run as root.[/red]")
        ctx.exit(1)
    if not tailscale_key:
        console.print("[red]fonfon setup requires a Tailscale auth key.[/red]")
        console.print(
            "Generate one at: https://login.tailscale.com/admin/settings/keys"
        )
        console.print("Then re-run: fonfon setup <user> --tailscale-key <key>")
        ctx.exit(1)
    if output_format == "json":
        report = run_setup(new_user, tailscale_key, traefik_cert_email)
        setup_json.render(report, console)
    else:
        setup_console.render_header(console)
        setup_console.render_action(console)

        def _runner(args, timeout=10, env=None):
            return run_streamed(args, console, timeout=timeout, env=env)

        report = run_setup(
            new_user,
            tailscale_key,
            traefik_cert_email,
            run=_runner,
            on_step_start=lambda step: setup_console.render_step_start(step, console),
            on_result=lambda r: setup_console.render_step(r, console),
        )
        setup_console.render_summary(report, console)
    ctx.exit(0 if report.ok else 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/cli.py tests/test_cli_setup.py
git commit -m "feat: add --traefik-cert-email flag; finish --tailscale-key rename"
```

---

### Task 10: Traefik deployment panel in console output

**Files:**
- Modify: `src/fonfon/output/setup_console.py`
- Test: `tests/test_setup_output.py`

**Interfaces:**
- Consumes: `SdciDeployment`, `TraefikDeployment` (Task 5).
- Produces: `_traefik_panel(deployment: TraefikDeployment) -> Panel`; `render_summary` renders a panel for *every* step carrying a deployment, dispatching by type.

- [ ] **Step 1: Write the failing tests** in `tests/test_setup_output.py`

First add `TraefikDeployment` to the existing top-of-file import (it currently
reads `from fonfon.models_setup import SdciDeployment, SetupReport, SetupStatus, StepResult`)
so it stays at module top (avoids ruff `E402`):

```python
from fonfon.models_setup import (
    SdciDeployment,
    SetupReport,
    SetupStatus,
    StepResult,
    TraefikDeployment,
)
```

Then append the test helpers and functions:

```python
def _report_with_traefik():
    return SetupReport(
        steps=[
            StepResult(
                title="Traefik",
                status=SetupStatus.INSTALLED,
                detail="installed",
                deployment=TraefikDeployment(
                    compose_file="/home/p/services/traefik/docker-compose.yml",
                    network="traefik",
                    dashboard_url="http://100.64.0.1:8080/dashboard/",
                    cert_email="you@example.com",
                ),
            ),
        ]
    )


def test_console_summary_renders_traefik_panel():
    out = _render_summary(_report_with_traefik())
    assert "Traefik deployed" in out
    assert "/home/p/services/traefik/docker-compose.yml" in out
    assert "traefik" in out
    assert "http://100.64.0.1:8080/dashboard/" in out
    assert "you@example.com" in out


def test_console_summary_renders_both_panels():
    report = SetupReport(
        steps=_report_with_deployment().steps + _report_with_traefik().steps
    )
    out = _render_summary(report)
    assert "sdci-server deployed" in out
    assert "Traefik deployed" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup_output.py -v`
Expected: FAIL — `ImportError: cannot import name 'TraefikDeployment'` is already resolved (Task 5), so failure is `AssertionError: 'Traefik deployed' not in out` (only the first/sdci deployment is rendered, and there is none here).

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/output/setup_console.py`

Update the import line:

```python
from fonfon.models_setup import (
    SdciDeployment,
    SetupReport,
    SetupStatus,
    StepResult,
    TraefikDeployment,
)
```

Add the Traefik panel builder after `_deployment_panel`:

```python
def _traefik_panel(deployment: TraefikDeployment) -> Panel:
    """Return a Panel summarising the Traefik deployment."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("compose", deployment.compose_file)
    table.add_row("network", deployment.network)
    table.add_row("dashboard", deployment.dashboard_url)
    table.add_row("cert email", deployment.cert_email)
    return Panel.fit(table, title="Traefik deployed", border_style="green")
```

Replace the tail of `render_summary` (the `deployment = next(...)` block) with a loop that renders each deployment by type:

```python
def render_summary(report: SetupReport, console: Console) -> None:
    """Print the counts footer and a panel for each deployed service."""
    installed = sum(1 for s in report.steps if s.status is SetupStatus.INSTALLED)
    skipped = sum(1 for s in report.steps if s.status is SetupStatus.SKIPPED)
    failed = sum(1 for s in report.steps if s.status is SetupStatus.FAILED)
    console.print(
        f"[green]{installed} installed[/green] · "
        f"[dim]{skipped} skipped[/dim] · "
        f"[red]{failed} failed[/red]"
    )
    for step in report.steps:
        deployment = step.deployment
        if isinstance(deployment, SdciDeployment):
            console.print(_deployment_panel(deployment))
        elif isinstance(deployment, TraefikDeployment):
            console.print(_traefik_panel(deployment))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup_output.py -v`
Expected: PASS (including the pre-existing sdci panel tests)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/output/setup_console.py tests/test_setup_output.py
git commit -m "feat: render a Traefik deployment panel in setup summary"
```

---

### Task 11: Documentation + version bump

**Files:**
- Create: `docs/manual/docs/services/traefik.md`
- Modify: `docs/manual/docs/commands/setup.md`
- Modify: `docs/manual/mkdocs.yml`
- Modify: `pyproject.toml`
- Regenerate: `docs/manual/site/` (committed build output)

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: a "Services → Traefik" manual page; updated setup steps table; `version = "0.5.0"`.

- [ ] **Step 1: Run the full suite to confirm a green baseline**

Run: `uv run pytest`
Expected: PASS (all tests from Tasks 1–10).

- [ ] **Step 2: Create the Traefik manual page**

Create `docs/manual/docs/services/traefik.md`:

````markdown
# Traefik

When `fonfon setup` is given `--traefik-cert-email`, it provisions
[Traefik](https://traefik.io) as the server's edge reverse proxy via Docker
Compose. Traefik serves your applications publicly on **:80** (HTTP→HTTPS
redirect + the ACME HTTP-01 challenge) and **:443** (TLS), while its
**dashboard is reachable only over the tailnet**.

## What gets created

Under the operator's home (`/home/<user>/services/traefik`):

| Path | Purpose |
|------|---------|
| `docker-compose.yml` | The Traefik service definition (image pinned to `traefik:v3.7.5`) |
| `traefik.yml` | Static configuration (entrypoints, providers, ACME resolver) |
| `acme/` | Stores `acme.json` (issued certificates) |
| `dynamic/` | File-provider directory for extra dynamic config (watched) |

Plus an **external Docker network** named `traefik`, and the running `traefik`
container.

## The dashboard is tailnet-only

The dashboard/API (`api.insecure: true`, port 8080 in the container) is
published on the host as `<tailnet_ip>:8080:8080` — bound solely to the
Tailscale interface. It is **not** reachable from the public internet. Browse to
`http://<tailnet_ip>:8080/dashboard/` from a device on your tailnet. Ports
`:80`/`:443` publish on all interfaces and remain public.

## Containers are not exposed by default

`providers.docker.exposedByDefault` is `false`. A container is only routed when
it opts in with `traefik.*` labels **and** joins the external `traefik` network.

## Exposing an application

In the application's own `docker-compose.yml`:

```yaml
services:
  myapp:
    image: ghcr.io/example/myapp:latest
    networks: [traefik]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.myapp.rule=Host(`app.example.com`)"
      - "traefik.http.routers.myapp.entrypoints=websecure"
      - "traefik.http.routers.myapp.tls.certresolver=le"
      # only if the app does NOT listen on port 80 inside the container:
      - "traefik.http.services.myapp.loadbalancer.server.port=3000"

networks:
  traefik:
    external: true
```

- `traefik.enable=true` — opt this container in.
- `rule=Host(...)` — the public hostname (its DNS A record must point at the VPS).
- `entrypoints=websecure` — serve on :443.
- `tls.certresolver=le` — obtain/renew a Let's Encrypt certificate (HTTP-01).

## Certificates

Certificates are issued via Let's Encrypt's **HTTP-01** challenge on the `web`
entrypoint and stored in `acme/acme.json`. The registration email is the value
of `--traefik-cert-email`. Port 80 must be publicly reachable for issuance and
renewal; the global HTTP→HTTPS redirect does not interfere — Traefik serves the
challenge path ahead of the redirect.

!!! note "Re-running setup"
    The Traefik step is idempotent on the *running container*: if `traefik` is
    already up, re-running `fonfon setup` reports it `skipped` and does **not**
    rewrite `traefik.yml` / `docker-compose.yml`. To change configuration, edit
    the file under `~/services/traefik` and run `docker compose up -d` there.
````

- [ ] **Step 3: Update the setup command page**

In `docs/manual/docs/commands/setup.md`:

First, correct the Tailscale flag/env names (the doc currently says
`--tailscale-auth-key` / `FONFON_TAILSCALE_AUTH_KEY`). Replace every occurrence
with `--tailscale-key` / `FONFON_TAILSCALE_KEY` (the warning admonition, the
Usage block's three commands, and the exit-code table row "No Tailscale auth key
provided" keeps its wording).

Then add a note about Traefik under the Usage section:

```markdown
To also deploy Traefik (reverse proxy with tailnet-only dashboard and Let's
Encrypt certificates), pass `--traefik-cert-email` (or set
`FONFON_TRAEFIK_CERT_EMAIL`):

​```bash
sudo fonfon setup deploy --tailscale-key <key> \
  --traefik-cert-email you@example.com
​```

See [Services → Traefik](../services/traefik.md) for the full model and the
application label cookbook.
```

Then append three rows to the provisioning-steps table:

```markdown
| 10 | **Traefik dirs** | Creates `/home/<user>/services/traefik/{,acme,dynamic}`, owned by the operator, mode `0700` (only when `--traefik-cert-email` is set) |
| 11 | **Traefik network** | Creates the external `traefik` Docker network so app stacks can attach |
| 12 | **Traefik** | Writes `docker-compose.yml` (image `traefik:v3.7.5`) + `traefik.yml`, then `docker compose up -d`; dashboard bound to `<tailnet-ip>:8080`, ACME HTTP-01 resolver `le` |
```

- [ ] **Step 4: Update the mkdocs nav**

In `docs/manual/mkdocs.yml`, add a Services section to `nav:` after Commands:

```yaml
nav:
  - Home: index.md
  - Getting Started: getting-started.md
  - Commands:
      - check: commands/check.md
      - setup: commands/setup.md
  - Services:
      - Traefik: services/traefik.md
```

- [ ] **Step 5: Bump the version**

In `pyproject.toml`, change:

```toml
version = "0.4.1"
```

to:

```toml
version = "0.5.0"
```

- [ ] **Step 6: Rebuild the committed docs site**

Run: `uv run mkdocs build -f docs/manual/mkdocs.yml`
Expected: builds into `docs/manual/site/` with no errors (a missing-page or nav warning means a path is wrong — fix it).

- [ ] **Step 7: Commit**

```bash
git add docs/manual/docs/services/traefik.md docs/manual/docs/commands/setup.md \
  docs/manual/mkdocs.yml docs/manual/site pyproject.toml
git commit -m "docs: document Traefik service; bump to 0.5.0"
```

---

## Final verification

- [ ] **Run the full unit suite:** `uv run pytest` → all green.
- [ ] **Run the linters/hooks:** `uv run pre-commit run --all-files` → all pass (ruff format + lint clean).
- [ ] **Sanity-check the CLI help:** `uv run fonfon setup --help` → shows `--tailscale-key` and `--traefik-cert-email`.
- [ ] **Optional end-to-end:** on a Debian VM (`make debian-demo` or `make test-integration`), run `sudo fonfon setup deploy --tailscale-key <key> --traefik-cert-email you@example.com` and confirm: `docker network ls` shows `traefik`; `docker ps` shows `traefik` running; the dashboard answers on `http://<tailnet-ip>:8080/dashboard/` but not on the public IP.

## Self-review notes (author)

- **Spec coverage:** CLI flag (Task 9), HTTP-01 resolver + email (Tasks 6/7), write-files-and-start lifecycle (Tasks 4/7), image pin `traefik:v3.7.5` (Task 6), `traefik` network + `exposedByDefault: false` (Tasks 3/6/7), dashboard-on-tailnet binding (Task 6), 3-step split (Task 7), models/output (Tasks 5/10), `--tailscale-key` rename (Task 9), docs + 0.5.0 bump (Task 11) — all mapped.
- **Type consistency:** `cert_email` is the parameter name through `render_static_config`, `TraefikStep`, `build_steps`, `run_setup`; the CLI option param is `traefik_cert_email` passed positionally. `TraefikPaths` field names (`base`, `acme`, `dynamic`, `compose_file`, `static_config`) are used identically in Tasks 1, 6, 7. `TraefikDeployment` fields (`compose_file`, `network`, `dashboard_url`, `cert_email`) match across Tasks 5, 7, 10.
- **Known limitation** (config not rewritten on re-run) is intentional and documented (Task 11, Step 2 note).
