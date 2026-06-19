# `fonfon setup` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add `fonfon setup <new_user>`, a root-only, idempotent provisioning command (create operator user; install Docker, Tailscale, pipx, sdci), and extend `check` to validate sdci via pipx.

**Architecture:** Mutating mirror of `check`. Each action is a `SetupStep` (`is_satisfied()` idempotency probe + `apply()` mutation). `run_setup` runs steps with continue-on-error into a `SetupReport`. New mutating boundary adapters (`Apt`, `Users`, `Pipx`) sit beside the read-only ones; all use the existing injectable `system/_run.py` runner.

**Tech Stack:** Python 3.14, click, rich, pydantic, pytest. Target: Debian (apt/dpkg).

**Reference:** `docs/specs/2026-06-19-setup-command-design.md` (design + step table). Mirror existing patterns in `src/fonfon/services/check.py`, `src/fonfon/output/console.py`, `src/fonfon/cli.py`, `src/fonfon/system/dpkg.py`, and `tests/fakes.py`.

**Conventions (CLAUDE.md):** Conventional Commits; run `pre-commit` before committing; no "Co-authored-by: Claude"; **do not commit unless told** (the maintainer commits); bump `pyproject.toml` version on every change; new features get a `docs/manual` entry.

---

## Shared notes

- Adapters take `run` via constructor defaulting to `fonfon.system._run.run` (same pattern as `Dpkg`/`Systemctl`). Tests inject fakes via `tests/fakes.py` (`fake_runner`, `completed`).
- `_run.run` already returns rc 127 for a missing binary and rc 1 on timeout without raising — rely on that for graceful "not installed".
- Global pipx env: `PIPX_HOME=/opt/pipx`, `PIPX_BIN_DIR=/usr/local/bin`. The `Pipx` adapter passes these via `env=` to the runner — so add an optional `env` arg to `_run.run` (Task 1).

---

## Task 1: setup DTOs + `_run` env support + `Pipx` adapter

**Files:**
- Modify: `src/fonfon/system/_run.py` (add optional `env`)
- Create: `src/fonfon/models_setup.py` (SetupStatus, StepResult, SetupReport)
- Create: `src/fonfon/system/pipx.py` (Pipx adapter)
- Test: `tests/test_models_setup.py`, `tests/test_pipx.py`, `tests/test_run.py` (extend)

- [ ] **Step 1: `_run` env — failing test** in `tests/test_run.py`:
```python
def test_run_passes_env_to_subprocess():
    # echo $FONFON_X via env; the child sees the merged env
    proc = run(["sh", "-c", "printf %s \"$FONFON_X\""], env={"FONFON_X": "abc"})
    assert proc.returncode == 0
    assert proc.stdout == "abc"
```
- [ ] **Step 2:** run → fails (TypeError: unexpected `env`).
- [ ] **Step 3: implement** — update `src/fonfon/system/_run.py`:
```python
import os
import subprocess

DEFAULT_TIMEOUT = 10

def run(args: list[str], timeout: int = DEFAULT_TIMEOUT, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a command, capturing text output; never raises on non-zero exit,
    a missing binary (rc 127), or a timeout (rc 1)."""
    merged = {**os.environ, **env} if env else None
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False,
                              timeout=timeout, env=merged)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr="")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")
```
- [ ] **Step 4:** run → passes; existing `_run` tests still pass.

- [ ] **Step 5: setup DTOs — failing test** `tests/test_models_setup.py`:
```python
from fonfon.models_setup import SetupReport, SetupStatus, StepResult

def _report(*statuses):
    return SetupReport(steps=[StepResult(title=f"S{i}", status=s) for i, s in enumerate(statuses)])

def test_status_values():
    assert SetupStatus.INSTALLED == "installed"
    assert SetupStatus.FAILED == "failed"

def test_ok_true_without_failures():
    assert _report(SetupStatus.INSTALLED, SetupStatus.SKIPPED).ok is True

def test_ok_false_with_failure():
    assert _report(SetupStatus.INSTALLED, SetupStatus.FAILED).ok is False
```
- [ ] **Step 6:** fails. **Step 7: implement** `src/fonfon/models_setup.py`:
```python
"""Presentation DTOs for `fonfon setup`."""
from enum import StrEnum
from pydantic import BaseModel

class SetupStatus(StrEnum):
    INSTALLED = "installed"
    SKIPPED = "skipped"
    FAILED = "failed"

class StepResult(BaseModel):
    title: str
    status: SetupStatus
    detail: str | None = None

class SetupReport(BaseModel):
    steps: list[StepResult]
    @property
    def ok(self) -> bool:
        return not any(s.status is SetupStatus.FAILED for s in self.steps)
```
- [ ] **Step 8:** passes.

- [ ] **Step 9: Pipx adapter — failing test** `tests/test_pipx.py`:
```python
from fonfon.system.pipx import Pipx
from tests.fakes import completed

def test_is_installed_true_when_listed():
    out = "sdci 1.2.3\nsomething 0.1\n"
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 0, out))
    assert pipx.is_installed("sdci") is True

def test_is_installed_false_when_absent():
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 0, "other 1.0\n"))
    assert pipx.is_installed("sdci") is False

def test_is_installed_false_when_pipx_missing():
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 127, "", ""))
    assert pipx.is_installed("sdci") is False

def test_install_global_invokes_pipx_with_global_env():
    seen = {}
    def run(args, timeout=10, env=None):
        seen["args"] = args; seen["env"] = env
        return completed(args, 0, "")
    Pipx(run=run).install_global("sdci")
    assert seen["args"][:2] == ["pipx", "install"]
    assert "sdci" in seen["args"]
    assert seen["env"]["PIPX_HOME"] == "/opt/pipx"
    assert seen["env"]["PIPX_BIN_DIR"] == "/usr/local/bin"
```
- [ ] **Step 10:** fails. **Step 11: implement** `src/fonfon/system/pipx.py`:
```python
"""Boundary adapter for pipx: global install + package-presence check."""
from collections.abc import Callable
from fonfon.system._run import run as _default_run

PIPX_HOME = "/opt/pipx"
PIPX_BIN_DIR = "/usr/local/bin"
_GLOBAL_ENV = {"PIPX_HOME": PIPX_HOME, "PIPX_BIN_DIR": PIPX_BIN_DIR}

class Pipx:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def is_installed(self, package: str) -> bool:
        proc = self._run(["pipx", "list", "--short"], env=_GLOBAL_ENV)
        if proc.returncode != 0:
            return False
        return any(line.split()[:1] == [package] for line in proc.stdout.splitlines() if line.strip())

    def install_global(self, package: str) -> None:
        proc = self._run(["pipx", "install", package], env=_GLOBAL_ENV)
        if proc.returncode != 0:
            raise RuntimeError(f"pipx install {package} failed: {proc.stderr.strip() or proc.stdout.strip()}")
```
- [ ] **Step 12:** passes; `uv run ruff check . && uv run ruff format .`; full suite green.

---

## Task 2: `Apt` and `Users` mutating adapters

**Files:**
- Create: `src/fonfon/system/apt.py`, `src/fonfon/system/users.py`
- Test: `tests/test_apt.py`, `tests/test_users.py`

- [ ] **Step 1: Apt — failing test** `tests/test_apt.py`:
```python
from fonfon.system.apt import Apt
from tests.fakes import completed

def _record():
    calls = []
    def run(args, timeout=10, env=None):
        calls.append((args, env)); return completed(args, 0, "")
    return calls, run

def test_install_uses_noninteractive_yes():
    calls, run = _record()
    Apt(run=run).install("ca-certificates", "curl")
    args, env = calls[-1]
    assert args[:3] == ["apt-get", "install", "-y"]
    assert "ca-certificates" in args and "curl" in args
    assert env["DEBIAN_FRONTEND"] == "noninteractive"

def test_install_raises_on_failure():
    def run(args, timeout=10, env=None): return completed(args, 100, "", "boom")
    import pytest
    with pytest.raises(RuntimeError):
        Apt(run=run).install("docker-ce")

def test_update_runs_apt_get_update():
    calls, run = _record()
    Apt(run=run).update()
    assert calls[-1][0] == ["apt-get", "update"]
```
- [ ] **Step 2:** fails. **Step 3: implement** `src/fonfon/system/apt.py`:
```python
"""Boundary adapter for apt: update, install, repo/keyring setup."""
from collections.abc import Callable
from fonfon.system._run import run as _default_run

_NONINTERACTIVE = {"DEBIAN_FRONTEND": "noninteractive"}
APT_TIMEOUT = 600  # installs can be slow

class Apt:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def _check(self, proc, what: str):
        if proc.returncode != 0:
            raise RuntimeError(f"{what} failed (rc {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")

    def update(self) -> None:
        self._check(self._run(["apt-get", "update"], timeout=APT_TIMEOUT, env=_NONINTERACTIVE), "apt-get update")

    def install(self, *packages: str) -> None:
        self._check(self._run(["apt-get", "install", "-y", *packages], timeout=APT_TIMEOUT,
                              env=_NONINTERACTIVE), f"apt-get install {' '.join(packages)}")

    def add_keyring(self, url: str, dest: str) -> None:
        self._check(self._run(["install", "-m", "0755", "-d", "/etc/apt/keyrings"]), "mkdir keyrings")
        self._check(self._run(["curl", "-fsSL", url, "-o", dest], timeout=APT_TIMEOUT), f"curl {url}")
        self._check(self._run(["chmod", "a+r", dest]), f"chmod {dest}")

    def add_repo(self, content: str, dest: str) -> None:
        self._check(self._run(["tee", dest], env={"REPO": content}), f"write {dest}")
```
> Note on `add_repo`: writing a file by shelling is awkward. Simpler and testable: have `add_repo` write via Python (`open(dest, "w").write(content)`) guarded so tests can monkeypatch — but that bypasses the `run` seam. **Decision:** implement `add_repo` by piping content to `tee` is brittle; instead write the file directly with `pathlib.Path(dest).write_text(content)` and unit-test by passing a `tmp_path` dest. Reviewer: prefer the direct-write form; drop the `REPO` env hack above and adjust the test accordingly.

- [ ] **Step 4:** passes.

- [ ] **Step 5: Users — failing test** `tests/test_users.py`:
```python
from fonfon.system.users import Users
from tests.fakes import completed

def test_exists_true_on_zero_exit():
    users = Users(run=lambda args, timeout=10, env=None: completed(args, 0, "1001\n"))
    assert users.exists("jon") is True

def test_exists_false_on_nonzero():
    users = Users(run=lambda args, timeout=10, env=None: completed(args, 1, "", "no such user"))
    assert users.exists("ghost") is False

def test_in_group_parses_id_nG():
    users = Users(run=lambda args, timeout=10, env=None: completed(args, 0, "jon sudo docker\n"))
    assert users.in_group("jon", "docker") is True
    assert users.in_group("jon", "wheel") is False

def test_create_invokes_useradd():
    seen = {}
    def run(args, timeout=10, env=None):
        seen["args"] = args; return completed(args, 0, "")
    Users(run=run).create("jon")
    assert seen["args"][0] == "useradd" and "jon" in seen["args"]

def test_add_to_group_invokes_usermod_aG():
    seen = {}
    def run(args, timeout=10, env=None):
        seen["args"] = args; return completed(args, 0, "")
    Users(run=run).add_to_group("jon", "docker")
    assert seen["args"] == ["usermod", "-aG", "docker", "jon"]
```
- [ ] **Step 6:** fails. **Step 7: implement** `src/fonfon/system/users.py`:
```python
"""Boundary adapter for local user/group management."""
from collections.abc import Callable
from fonfon.system._run import run as _default_run

class Users:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def exists(self, user: str) -> bool:
        return self._run(["id", "-u", user]).returncode == 0

    def in_group(self, user: str, group: str) -> bool:
        proc = self._run(["id", "-nG", user])
        return proc.returncode == 0 and group in proc.stdout.split()

    def create(self, user: str) -> None:
        proc = self._run(["useradd", "-m", "-s", "/bin/bash", user])
        if proc.returncode != 0:
            raise RuntimeError(f"useradd {user} failed: {proc.stderr.strip()}")

    def add_to_group(self, user: str, group: str) -> None:
        proc = self._run(["usermod", "-aG", group, user])
        if proc.returncode != 0:
            raise RuntimeError(f"usermod -aG {group} {user} failed: {proc.stderr.strip()}")
```
- [ ] **Step 8:** passes; ruff clean; full suite green.

---

## Task 3: `SetupStep` base + the six steps

**Files:**
- Create: `src/fonfon/services/setup_steps.py`
- Test: `tests/test_setup_steps.py`

Each step takes its adapters via constructor (real defaults) so tests inject fakes.

- [ ] **Step 1: failing tests** `tests/test_setup_steps.py` — cover each step's `is_satisfied` true/false and that `apply` issues the right adapter calls. Example for the User and Docker-group steps (write similar for Tailscale/pipx/sdci/docker):
```python
from fonfon.services.setup_steps import (
    UserStep, DockerGroupStep, PipxStep, SdciStep, TailscaleStep, DockerStep,
)

class FakeUsers:
    def __init__(self, existing=(), groups=None):
        self.existing = set(existing); self.groups = groups or {}; self.calls = []
    def exists(self, u): return u in self.existing
    def in_group(self, u, g): return g in self.groups.get(u, [])
    def create(self, u): self.calls.append(("create", u)); self.existing.add(u)
    def add_to_group(self, u, g): self.calls.append(("add", u, g)); self.groups.setdefault(u, []).append(g)

def test_user_step_satisfied_when_exists_and_in_sudo():
    users = FakeUsers(existing=["jon"], groups={"jon": ["sudo"]})
    assert UserStep("jon", users=users).is_satisfied() is True

def test_user_step_apply_creates_and_adds_sudo():
    users = FakeUsers()
    UserStep("jon", users=users).apply()
    assert ("create", "jon") in users.calls
    assert ("add", "jon", "sudo") in users.calls

def test_docker_group_step_apply_adds_docker():
    users = FakeUsers(existing=["jon"])
    DockerGroupStep("jon", users=users).apply()
    assert ("add", "jon", "docker") in users.calls
```
For Docker/Tailscale/pipx/sdci steps, fake `Dpkg`/`Apt`/`Pipx` and assert `is_satisfied` reads the right probe and `apply` calls the right adapter (e.g. `SdciStep.apply()` calls `Pipx.install_global("sdci")`; `PipxStep.apply()` calls `Apt.install("python3-pipx")`; `TailscaleStep.apply()` runs the install script via the injected runner; `DockerStep.apply()` calls the apt-repo sequence).

- [ ] **Step 2:** fails. **Step 3: implement** `src/fonfon/services/setup_steps.py`:
```python
"""The concrete provisioning steps for `fonfon setup`."""
from abc import ABC, abstractmethod
from collections.abc import Callable

from fonfon.system import probes
from fonfon.system._run import run as _default_run
from fonfon.system.apt import Apt
from fonfon.system.dpkg import Dpkg
from fonfon.system.pipx import Pipx
from fonfon.system.users import Users

DOCKER_PACKAGES = ["docker-ce", "docker-ce-cli", "containerd.io",
                   "docker-buildx-plugin", "docker-compose-plugin"]
TAILSCALE_INSTALL_URL = "https://tailscale.com/install.sh"
DOCKER_GPG_URL = "https://download.docker.com/linux/debian/gpg"
DOCKER_KEYRING = "/etc/apt/keyrings/docker.asc"
DOCKER_REPO_FILE = "/etc/apt/sources.list.d/docker.list"

class SetupStep(ABC):
    title: str
    @abstractmethod
    def is_satisfied(self) -> bool: ...
    @abstractmethod
    def apply(self) -> None: ...

class UserStep(SetupStep):
    title = "User"
    def __init__(self, user: str, users: Users | None = None):
        self._user = user; self._users = users or Users()
    def is_satisfied(self) -> bool:
        return self._users.exists(self._user) and self._users.in_group(self._user, "sudo")
    def apply(self) -> None:
        if not self._users.exists(self._user):
            self._users.create(self._user)
        self._users.add_to_group(self._user, "sudo")

class DockerStep(SetupStep):
    title = "Docker"
    def __init__(self, apt: Apt | None = None, dpkg: Dpkg | None = None,
                 read_os_release: Callable = probes.read_os_release, run: Callable = _default_run):
        self._apt = apt or Apt(); self._dpkg = dpkg or Dpkg()
        self._read_os_release = read_os_release; self._run = run
    def is_satisfied(self) -> bool:
        return self._dpkg.query("docker-ce").installed
    def apply(self) -> None:
        self._apt.install("ca-certificates", "curl")
        self._apt.add_keyring(DOCKER_GPG_URL, DOCKER_KEYRING)
        arch = self._run(["dpkg", "--print-architecture"]).stdout.strip()
        codename = self._read_os_release().get("VERSION_CODENAME", "")
        repo = (f"deb [arch={arch} signed-by={DOCKER_KEYRING}] "
                f"https://download.docker.com/linux/debian {codename} stable\n")
        self._apt.add_repo(repo, DOCKER_REPO_FILE)
        self._apt.update()
        self._apt.install(*DOCKER_PACKAGES)

class DockerGroupStep(SetupStep):
    title = "Docker group"
    def __init__(self, user: str, users: Users | None = None):
        self._user = user; self._users = users or Users()
    def is_satisfied(self) -> bool:
        return self._users.in_group(self._user, "docker")
    def apply(self) -> None:
        self._users.add_to_group(self._user, "docker")

class TailscaleStep(SetupStep):
    title = "Tailscale"
    def __init__(self, dpkg: Dpkg | None = None, run: Callable = _default_run):
        self._dpkg = dpkg or Dpkg(); self._run = run
    def is_satisfied(self) -> bool:
        return self._dpkg.query("tailscale").installed
    def apply(self) -> None:
        proc = self._run(["sh", "-c", f"curl -fsSL {TAILSCALE_INSTALL_URL} | sh"], timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"tailscale install failed: {proc.stderr.strip() or proc.stdout.strip()}")

class PipxStep(SetupStep):
    title = "pipx"
    def __init__(self, apt: Apt | None = None, dpkg: Dpkg | None = None):
        self._apt = apt or Apt(); self._dpkg = dpkg or Dpkg()
    def is_satisfied(self) -> bool:
        return self._dpkg.query("python3-pipx").installed
    def apply(self) -> None:
        self._apt.install("python3-pipx")

class SdciStep(SetupStep):
    title = "sdci"
    def __init__(self, pipx: Pipx | None = None):
        self._pipx = pipx or Pipx()
    def is_satisfied(self) -> bool:
        return self._pipx.is_installed("sdci")
    def apply(self) -> None:
        self._pipx.install_global("sdci")
```
- [ ] **Step 4:** passes; ruff clean; suite green.

---

## Task 4: `run_setup` use-case + policy

**Files:**
- Create: `src/fonfon/services/setup.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: failing tests** `tests/test_setup.py`:
```python
from fonfon.models_setup import SetupStatus
from fonfon.services.setup import run_step, build_steps
from fonfon.services.setup_steps import SetupStep

class FakeStep(SetupStep):
    def __init__(self, title, satisfied=False, boom=False):
        self.title = title; self._satisfied = satisfied; self._boom = boom; self.applied = False
    def is_satisfied(self): return self._satisfied
    def apply(self):
        if self._boom: raise RuntimeError("nope")
        self.applied = True

def test_satisfied_step_is_skipped():
    r = run_step(FakeStep("X", satisfied=True))
    assert r.status is SetupStatus.SKIPPED

def test_unsatisfied_step_applies_and_is_installed():
    step = FakeStep("X")
    r = run_step(step)
    assert r.status is SetupStatus.INSTALLED and step.applied is True

def test_failing_step_is_failed_with_detail():
    r = run_step(FakeStep("X", boom=True))
    assert r.status is SetupStatus.FAILED and "nope" in r.detail

def test_build_steps_order_and_titles():
    titles = [s.title for s in build_steps("jon")]
    assert titles == ["User", "Docker", "Docker group", "Tailscale", "pipx", "sdci"]
```
- [ ] **Step 2:** fails. **Step 3: implement** `src/fonfon/services/setup.py`:
```python
"""The `setup` use-case: run provisioning steps with continue-on-error."""
from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.services.setup_steps import (
    DockerGroupStep, DockerStep, PipxStep, SdciStep, SetupStep, TailscaleStep, UserStep,
)

def build_steps(new_user: str) -> list[SetupStep]:
    return [UserStep(new_user), DockerStep(), DockerGroupStep(new_user),
            TailscaleStep(), PipxStep(), SdciStep()]

def run_step(step: SetupStep) -> StepResult:
    if step.is_satisfied():
        return StepResult(title=step.title, status=SetupStatus.SKIPPED, detail="already present")
    try:
        step.apply()
        return StepResult(title=step.title, status=SetupStatus.INSTALLED, detail="installed")
    except Exception as exc:  # continue-on-error
        return StepResult(title=step.title, status=SetupStatus.FAILED, detail=str(exc))

def run_setup(new_user: str) -> SetupReport:
    return SetupReport(steps=[run_step(s) for s in build_steps(new_user)])
```
- [ ] **Step 4:** passes.

---

## Task 5: setup renderers + CLI `setup` command (root gate)

**Files:**
- Create: `src/fonfon/output/setup_console.py`, `src/fonfon/output/setup_json.py`
- Modify: `src/fonfon/cli.py`
- Test: `tests/test_setup_output.py`, `tests/test_cli_setup.py`

- [ ] **Step 1: renderer tests** `tests/test_setup_output.py` (mirror `tests/test_output.py`):
```python
import json as json_module
from io import StringIO
from rich.console import Console
from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.output import setup_console, setup_json

def _report():
    return SetupReport(steps=[
        StepResult(title="User", status=SetupStatus.INSTALLED, detail="installed"),
        StepResult(title="Docker", status=SetupStatus.FAILED, detail="boom"),
    ])

def _render(renderer):
    buf = StringIO(); renderer.render(_report(), Console(file=buf, force_terminal=False, width=100))
    return buf.getvalue()

def test_console_lists_steps_and_statuses():
    out = _render(setup_console)
    assert "User" in out and "Docker" in out and "INSTALLED" in out and "FAILED" in out

def test_json_roundtrips():
    data = json_module.loads(_render(setup_json))
    assert data["steps"][1]["status"] == "failed"
```
- [ ] **Step 2:** fails. **Step 3: implement** the renderers (mirror `output/console.py` + `output/json.py`):
`setup_console.render(report, console)` — print `build_header(get_version())`, a `Table` (Step/Status/Detail) with a style map `{INSTALLED: ("green","✓ INSTALLED"), SKIPPED: ("dim","– SKIPPED"), FAILED: ("red","✗ FAILED")}`, then a summary footer counting each. `setup_json.render(report, console)` — `console.print_json(report.model_dump_json())`.
- [ ] **Step 4:** renderer tests pass.

- [ ] **Step 5: CLI tests** `tests/test_cli_setup.py`:
```python
import json as json_module
from click.testing import CliRunner
from fonfon.cli import main
from fonfon.models_setup import SetupReport, SetupStatus, StepResult

def _ok_report():
    return SetupReport(steps=[StepResult(title="User", status=SetupStatus.SKIPPED)])

def test_setup_requires_root(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 1000)
    result = CliRunner().invoke(main, ["setup", "jon"])
    assert result.exit_code != 0
    assert "root" in result.output.lower()

def test_setup_runs_as_root_exit_zero(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    monkeypatch.setattr("fonfon.cli.run_setup", lambda u: _ok_report())
    result = CliRunner().invoke(main, ["setup", "jon"])
    assert result.exit_code == 0

def test_setup_exit_one_on_failure(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    failed = SetupReport(steps=[StepResult(title="Docker", status=SetupStatus.FAILED)])
    monkeypatch.setattr("fonfon.cli.run_setup", lambda u: failed)
    result = CliRunner().invoke(main, ["setup", "jon"])
    assert result.exit_code == 1

def test_setup_json(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    monkeypatch.setattr("fonfon.cli.run_setup", lambda u: _ok_report())
    result = CliRunner().invoke(main, ["setup", "jon", "--output", "json"])
    assert json_module.loads(result.output)["steps"][0]["status"] == "skipped"
```
- [ ] **Step 6:** fails. **Step 7: implement** — add to `src/fonfon/cli.py` (keep existing imports/commands; add `import os`):
```python
from fonfon.output import setup_console, setup_json
from fonfon.services.setup import run_setup

@main.command()
@click.argument("new_user")
@click.option("-o", "--output", "output_format",
              type=click.Choice(["console", "json"]), default="console", help="Output format.")
@click.pass_context
def setup(ctx: click.Context, new_user: str, output_format: str) -> None:
    """Provision this server (Docker, Tailscale, pipx, sdci) and an operator user."""
    if os.geteuid() != 0:
        Console().print("[red]fonfon setup must be run as root.[/red]")
        ctx.exit(1)
    report = run_setup(new_user)
    console = Console()
    if output_format == "json":
        setup_json.render(report, console)
    else:
        setup_console.render(report, console)
    ctx.exit(0 if report.ok else 1)
```
- [ ] **Step 8:** passes; existing CLI tests still green.

---

## Task 6: extend `check` with the sdci (pipx) item

**Files:**
- Modify: `src/fonfon/services/check.py`
- Test: `tests/test_check.py` (extend)

- [ ] **Step 1: failing test** in `tests/test_check.py`:
```python
def test_packages_section_includes_sdci_via_pipx(monkeypatch):
    # build_report gains an sdci item sourced from a pipx check
    from fonfon.services.check import build_report
    # ... construct base DTOs as the existing _base() helper does, plus sdci_installed flag
```
Concretely: add an `sdci_installed: bool` parameter to `build_report` (defaulting via `run_check`), and assert the Packages section contains an `sdci` item that is `OK` when True and `FAIL` when False. Add two tests (installed/not).
- [ ] **Step 2:** fails. **Step 3: implement** — in `src/fonfon/services/check.py`:
  - `run_check`: after building `packages`, compute `sdci_installed = Pipx().is_installed("sdci")` and pass it to `build_report`.
  - `build_report(..., sdci_installed: bool)`: in `_packages_section`, append a `CheckItem(key="package.sdci", label="sdci", status=OK if sdci_installed else FAIL, detail="installed (pipx)" if sdci_installed else "not installed")`. When `packages is None` (unsupported distro) still report the sdci row (pipx is distro-agnostic) — keep the existing SKIP row for dpkg packages and add the sdci row.
- [ ] **Step 4:** passes; all existing check tests still green.

---

## Task 7: docs, manual, version bump, integration

**Files:**
- Create: `docs/manual/docs/commands/setup.md`; Modify: `docs/manual/mkdocs.yml`, `CLAUDE.md`, `pyproject.toml`, `tests/integration/test_smoke.py`

- [ ] **Step 1: manual page** `docs/manual/docs/commands/setup.md` — usage (`fonfon setup <new_user>`, `--output json`), the root requirement, the step table, idempotency + exit-code note, and that sdci is installed globally via pipx. Add a `Commands > setup` nav entry in `mkdocs.yml`.
- [ ] **Step 2:** `uv run mkdocs build --strict -f docs/manual/mkdocs.yml` → clean.
- [ ] **Step 3: CLAUDE.md** — under "Layered design", add one line noting the mutating counterpart: `setup` = `SetupStep` (is_satisfied + apply) → `run_setup` (continue-on-error) → `SetupReport`; mutating adapters `Apt`/`Users`/`Pipx` beside the read-only probes.
- [ ] **Step 4: version bump** `pyproject.toml` `0.1.3 → 0.2.0` (minor — new feature), then `uv sync`. Confirm `uv run fonfon --version` shows `0.2.0` and the version test passes.
- [ ] **Step 5: integration smoke** — append to `tests/integration/test_smoke.py` a `@pytest.mark.integration` test that runs `sudo {vm_run.scie} setup ituser --output json` and asserts it emitted JSON with `"steps"` and that a second run reports the steps as `skipped` (idempotency). Mirror the existing fixture usage.
- [ ] **Step 6:** confirm integration tests are deselected by default (`uv run pytest tests/integration` → skipped).

---

## Final verification
- [ ] `uv run pytest -v` green; `uv run ruff check . && uv run ruff format --check .` clean; `uv run pre-commit run --all-files` passes.
- [ ] `uv run mkdocs build --strict -f docs/manual/mkdocs.yml`.
- [ ] `uv run fonfon setup test` (non-root dev host) exits non-zero with the root message; `uv run fonfon check` still renders (now with an sdci row).
- [ ] Leave uncommitted for the maintainer.

## Self-review notes
- **Spec coverage:** root gate (T5), user+groups (T3 UserStep/DockerGroupStep), docker apt-repo (T3 DockerStep + T2 Apt), tailscale script (T3), pipx (T3/T2), sdci global pipx (T1 Pipx + T3 SdciStep), continue-on-error + exit (T4), output (T5), check sdci item (T6), docs+manual+version (T7).
- **Type consistency:** `_run.run(..., env=)` added in T1 and used by Apt/Pipx/Users tests' fake signatures `(args, timeout=10, env=None)`. `Pipx.is_installed`/`install_global`, `Users.*`, `Apt.*` names match across producer and steps. `SetupStatus`/`StepResult`/`SetupReport` consistent.
- **Open nit for the implementer/reviewer:** `Apt.add_repo` should write the file directly (`Path(dest).write_text(content)`), not via `tee`/env — see the Task 2 note.
