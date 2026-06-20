# sdci Directories + Deploy Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `fonfon setup` creates the operator's `/home/<user>/services/sdci/{tasks,uploads}` tree (operator-owned, `0700`), runs `sdci-server setup` with `--uploads-dir`/`--tasks-dir`/`--user`, surfaces a rich deploy panel (project/tasks/uploads/token), and `fonfon check` reports the `sdci-server` systemd unit.

**Architecture:** A new `Fs` boundary adapter + `sdci_paths` helper back a new idempotent `SdciDirsStep` placed before the existing `sdci config` step. `Sdci.setup` and `SdciConfigStep` gain the dirs + operator user; the flat `StepResult.token` is consolidated into a structured `SdciDeployment` carried on `StepResult.deployment` and rendered as a rich panel. `check`'s systemd Services list gains `sdci-server`.

**Tech Stack:** Python 3.14, click, rich (Panel/Table), pydantic; `secrets`; pytest with injected fakes (`tests/fakes.py::completed`).

**Spec:** `docs/specs/2026-06-20-sdci-dirs-and-deploy-output-design.md`

---

## File Structure

**New files:**
- `src/fonfon/services/sdci_paths.py` — `SdciPaths` model + `sdci_paths(user)`.
- `src/fonfon/system/fs.py` — `Fs` adapter: `exists(path)`, `make_dir(path, owner, mode)`.
- `tests/test_sdci_paths.py`, `tests/test_fs.py`.

**Modified files:**
- `src/fonfon/services/setup_steps.py` — new `SdciDirsStep`; `SdciConfigStep` gains `user`+`paths`, passes dirs+user to `Sdci.setup`, and (Task 5) produces an `SdciDeployment`; `SetupStep.token` → `deployment`.
- `src/fonfon/system/sdci.py` — `Sdci.setup` gains `uploads_dir`, `tasks_dir`, `user`.
- `src/fonfon/services/setup.py` — `build_steps` wires `SdciDirsStep`+`SdciConfigStep` with derived paths; `run_step` carries `deployment`.
- `src/fonfon/models_setup.py` — `SdciDeployment` model; `StepResult.token` → `deployment`.
- `src/fonfon/output/setup_console.py` — render a deploy panel instead of the token line.
- `src/fonfon/services/check.py` — add `sdci-server` to `SERVICES`.
- `docs/manual/docs/commands/setup.md`, `docs/manual/docs/commands/check.md` — docs.
- `pyproject.toml` — bump `0.3.1 → 0.4.0`.
- Tests updated where signatures change: `tests/test_sdci.py`, `tests/test_setup_steps.py`, `tests/test_setup.py`, `tests/test_models_setup.py`, `tests/test_setup_output.py`, `tests/test_check.py`.

**Conventions (CLAUDE.md):** conventional commits; **no** "Co-authored-by" trailer; run `uv run pre-commit run --all-files` before each commit; `uv run pytest`. For raise-path tests use `pytest.raises`. One commit per task with the message given.

---

### Task 1: `sdci_paths` helper

**Files:** Create `src/fonfon/services/sdci_paths.py`; Test `tests/test_sdci_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sdci_paths.py
from fonfon.services.sdci_paths import sdci_paths


def test_sdci_paths_derives_from_user():
    p = sdci_paths("preludian")
    assert p.base == "/home/preludian/services/sdci"
    assert p.tasks == "/home/preludian/services/sdci/tasks"
    assert p.uploads == "/home/preludian/services/sdci/uploads"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sdci_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.services.sdci_paths'`.

- [ ] **Step 3: Implement**

```python
# src/fonfon/services/sdci_paths.py
"""Derive the operator's sdci service-directory paths from a username."""

from pydantic import BaseModel


class SdciPaths(BaseModel):
    base: str
    tasks: str
    uploads: str


def sdci_paths(user: str) -> SdciPaths:
    """Return the sdci service-dir tree for `user` under their home directory."""
    base = f"/home/{user}/services/sdci"
    return SdciPaths(base=base, tasks=f"{base}/tasks", uploads=f"{base}/uploads")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_sdci_paths.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/services/sdci_paths.py tests/test_sdci_paths.py
git commit -m "feat: add sdci_paths helper deriving the service-dir tree from a user"
```

---

### Task 2: `Fs` boundary adapter

**Files:** Create `src/fonfon/system/fs.py`; Test `tests/test_fs.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fs.py
import pytest

from fonfon.system.fs import Fs
from tests.fakes import completed


def test_make_dir_invokes_install_with_owner_and_mode():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        return completed(args, 0, "")

    Fs(run=run).make_dir("/home/u/services/sdci", "u", "0700")
    assert seen["args"] == [
        "install", "-d", "-o", "u", "-g", "u", "-m", "0700",
        "/home/u/services/sdci",
    ]


def test_make_dir_raises_on_failure():
    fs = Fs(run=lambda args, timeout=10, env=None: completed(args, 1, "", "boom"))
    with pytest.raises(RuntimeError, match="boom"):
        fs.make_dir("/x", "u", "0700")


def test_exists_reflects_probe():
    fs = Fs(exists=lambda path: path == "/yes")
    assert fs.exists("/yes") is True
    assert fs.exists("/no") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_fs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.system.fs'`.

- [ ] **Step 3: Implement**

```python
# src/fonfon/system/fs.py
"""Boundary adapter for filesystem directory creation."""

import os
from collections.abc import Callable

from fonfon.system._run import run as _default_run


class Fs:
    def __init__(
        self,
        run: Callable = _default_run,
        exists: Callable[[str], bool] = os.path.exists,
    ):
        self._run = run
        self._exists = exists

    def exists(self, path: str) -> bool:
        return self._exists(path)

    def make_dir(self, path: str, owner: str, mode: str) -> None:
        proc = self._run(
            ["install", "-d", "-o", owner, "-g", owner, "-m", mode, path]
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"mkdir {path} failed (rc {proc.returncode}): {detail}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_fs.py -v` → PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/system/fs.py tests/test_fs.py
git commit -m "feat: add Fs boundary adapter (install -d directory creation)"
```

---

### Task 3: `SdciDirsStep`

**Files:** Modify `src/fonfon/services/setup_steps.py` (imports + new class at end); Test `tests/test_setup_steps.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_setup_steps.py`:

```python
from fonfon.services.sdci_paths import sdci_paths
from fonfon.services.setup_steps import SdciDirsStep


class FakeFs:
    def __init__(self, existing=()):
        self._existing = set(existing)
        self.made = []

    def exists(self, path):
        return path in self._existing

    def make_dir(self, path, owner, mode):
        self.made.append((path, owner, mode))
        self._existing.add(path)


def test_sdci_dirs_satisfied_when_dirs_exist():
    paths = sdci_paths("preludian")
    fs = FakeFs(existing=(paths.tasks, paths.uploads))
    assert SdciDirsStep("preludian", paths, fs=fs).is_satisfied() is True


def test_sdci_dirs_not_satisfied_when_missing():
    paths = sdci_paths("preludian")
    assert SdciDirsStep("preludian", paths, fs=FakeFs()).is_satisfied() is False


def test_sdci_dirs_apply_creates_base_tasks_uploads_owned_0700():
    paths = sdci_paths("preludian")
    fs = FakeFs()
    SdciDirsStep("preludian", paths, fs=fs).apply()
    assert fs.made == [
        (paths.base, "preludian", "0700"),
        (paths.tasks, "preludian", "0700"),
        (paths.uploads, "preludian", "0700"),
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_setup_steps.py -v`
Expected: FAIL — `ImportError: cannot import name 'SdciDirsStep'`.

- [ ] **Step 3: Implement** in `src/fonfon/services/setup_steps.py`.

Add imports near the existing top imports:
```python
from fonfon.services.sdci_paths import SdciPaths
from fonfon.system.fs import Fs
```
Add a module constant near the other constants (after `SDCI_EXECUTABLE`):
```python
SDCI_DIR_MODE = "0700"
```
Append the class at the END of the file:
```python
class SdciDirsStep(SetupStep):
    """Create the operator's sdci service directories (tasks, uploads)."""

    title = "sdci dirs"

    def __init__(self, user: str, paths: SdciPaths, fs: Fs | None = None) -> None:
        self._user = user
        self._paths = paths
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        return self._fs.exists(self._paths.tasks) and self._fs.exists(
            self._paths.uploads
        )

    def apply(self) -> None:
        for path in (self._paths.base, self._paths.tasks, self._paths.uploads):
            self._fs.make_dir(path, self._user, SDCI_DIR_MODE)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_setup_steps.py -v` → PASS (existing step tests still green + 3 new).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/services/setup_steps.py tests/test_setup_steps.py
git commit -m "feat: add SdciDirsStep creating the operator sdci service dirs"
```

---

### Task 4: Pass dirs + operator user into `sdci-server setup`; wire the dirs step

This task keeps the existing `token` output mechanism (Task 5 migrates it). It makes `Sdci.setup` take the dirs + user, gives `SdciConfigStep` the `user`+`paths`, and appends `SdciDirsStep` + the updated `SdciConfigStep` in `build_steps`.

**Files:** Modify `src/fonfon/system/sdci.py`, `src/fonfon/services/setup_steps.py` (`SdciConfigStep`), `src/fonfon/services/setup.py` (`build_steps`). Tests: `tests/test_sdci.py`, `tests/test_setup_steps.py`, `tests/test_setup.py`.

- [ ] **Step 1: Update the tests.**

In `tests/test_sdci.py`, replace `test_setup_invokes_sdci_server_setup` and `test_setup_raises_on_failure` with:
```python
def test_setup_invokes_sdci_server_setup():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    Sdci(run=run).setup("100.64.0.1", "tok", "/u/up", "/u/tk", "preludian")
    assert seen["args"] == [
        "sdci-server", "setup", "--ip", "100.64.0.1", "--token", "tok",
        "--uploads-dir", "/u/up", "--tasks-dir", "/u/tk", "--user", "preludian",
    ]
    assert seen["timeout"] >= 60


def test_setup_raises_on_failure():
    s = Sdci(run=lambda args, timeout=10, env=None: completed(args, 1, "", "nope"))
    with pytest.raises(RuntimeError, match="nope"):
        s.setup("ip", "tok", "/up", "/tk", "u")
```

In `tests/test_setup_steps.py`: (a) update `FakeSdci.setup` to accept the new args, and (b) replace the four `SdciConfigStep` tests. Change `FakeSdci`:
```python
class FakeSdci:
    def __init__(self, configured=False):
        self._configured = configured
        self.setup_args = None

    def is_configured(self):
        return self._configured

    def setup(self, ip, token, uploads_dir, tasks_dir, user):
        self.setup_args = (ip, token, uploads_dir, tasks_dir, user)
```
Replace the four `SdciConfigStep` tests (`test_sdci_config_*`) with:
```python
PATHS = sdci_paths("preludian")


def test_sdci_config_satisfied_when_configured():
    step = SdciConfigStep(
        "preludian", PATHS,
        tailscale=FakeTailscale(ip="100.64.0.1"), sdci=FakeSdci(configured=True),
    )
    assert step.is_satisfied() is True


def test_sdci_config_not_satisfied_when_unconfigured():
    step = SdciConfigStep(
        "preludian", PATHS,
        tailscale=FakeTailscale(ip="100.64.0.1"), sdci=FakeSdci(configured=False),
    )
    assert step.is_satisfied() is False


def test_sdci_config_apply_configures_with_dirs_and_user():
    ts = FakeTailscale(ip="100.64.0.1")
    sdci = FakeSdci()
    step = SdciConfigStep(
        "preludian", PATHS, tailscale=ts, sdci=sdci, token_factory=lambda: "T" * 42
    )
    step.apply()
    assert sdci.setup_args == (
        "100.64.0.1", "T" * 42, PATHS.uploads, PATHS.tasks, "preludian",
    )
    assert step.token == "T" * 42


def test_sdci_config_apply_raises_without_ip():
    step = SdciConfigStep(
        "preludian", PATHS,
        tailscale=FakeTailscale(ip=None), sdci=FakeSdci(), token_factory=lambda: "T",
    )
    with pytest.raises(RuntimeError):
        step.apply()
```
(`sdci_paths` is already imported from Task 3.)

In `tests/test_setup.py`, update `test_build_steps_with_auth_key_appends_service_steps` to include `"sdci dirs"`:
```python
def test_build_steps_with_auth_key_appends_service_steps():
    titles = [s.title for s in build_steps("jon", "tskey-abc")]
    assert titles == [
        "User", "Docker", "Docker group", "Tailscale", "pipx", "sdci",
        "Tailscale up", "sdci dirs", "sdci config",
    ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_sdci.py tests/test_setup_steps.py tests/test_setup.py -v`
Expected: FAIL — `Sdci.setup` takes 2 args not 5; `SdciConfigStep` takes no `user`/`paths`; build order lacks `sdci dirs`.

- [ ] **Step 3: Implement.**

In `src/fonfon/system/sdci.py`, replace `setup`:
```python
    def setup(
        self, ip: str, token: str, uploads_dir: str, tasks_dir: str, user: str
    ) -> None:
        proc = self._run(
            [
                "sdci-server", "setup",
                "--ip", ip, "--token", token,
                "--uploads-dir", uploads_dir, "--tasks-dir", tasks_dir,
                "--user", user,
            ],
            timeout=SDCI_SETUP_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"sdci-server setup failed (rc {proc.returncode}): {detail}"
            )
```

In `src/fonfon/services/setup_steps.py`, replace the whole `SdciConfigStep` class with (note new first two params `user`, `paths`; `apply` still sets `self.token`):
```python
class SdciConfigStep(SetupStep):
    """Configure sdci-server against the tailnet IP with a generated token."""

    title = "sdci config"

    def __init__(
        self,
        user: str,
        paths: SdciPaths,
        tailscale: Tailscale | None = None,
        sdci: Sdci | None = None,
        token_factory: Callable[[], str] = generate_token,
    ) -> None:
        self._user = user
        self._paths = paths
        self._tailscale = tailscale or Tailscale()
        self._sdci = sdci or Sdci()
        self._token_factory = token_factory

    def is_satisfied(self) -> bool:
        return self._sdci.is_configured()

    def apply(self) -> None:
        ip = self._tailscale.ipv4()
        if ip is None:
            raise RuntimeError(
                "no Tailscale IPv4 available; is `tailscale up` complete?"
            )
        token = self._token_factory()
        self._sdci.setup(
            ip, token, self._paths.uploads, self._paths.tasks, self._user
        )
        self.token = token
```

In `src/fonfon/services/setup.py`: add imports — `SdciDirsStep` to the `setup_steps` import block, plus:
```python
from fonfon.services.sdci_paths import sdci_paths
from fonfon.system.fs import Fs
```
Replace the `if auth_key:` block inside `build_steps`:
```python
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
    return steps
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_sdci.py tests/test_setup_steps.py tests/test_setup.py -v` → PASS. Then full suite `uv run pytest -q` → all green.

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/system/sdci.py src/fonfon/services/setup_steps.py src/fonfon/services/setup.py tests/test_sdci.py tests/test_setup_steps.py tests/test_setup.py
git commit -m "feat: provision sdci dirs and run sdci-server setup with --uploads-dir/--tasks-dir/--user"
```

---

### Task 5: Consolidate token into `SdciDeployment` and render a deploy panel

Replaces the flat `StepResult.token` with a structured `SdciDeployment{base_dir, tasks_dir, uploads_dir, token}`, carried through `run_step` and rendered as a rich panel (console) / nested object (JSON).

**Files:** Modify `src/fonfon/models_setup.py`, `src/fonfon/services/setup_steps.py` (`SetupStep` base + `SdciConfigStep.apply`), `src/fonfon/services/setup.py` (`run_step`), `src/fonfon/output/setup_console.py`. Tests: `tests/test_models_setup.py`, `tests/test_setup.py`, `tests/test_setup_steps.py`, `tests/test_setup_output.py`.

- [ ] **Step 1: Update/add tests.**

In `tests/test_models_setup.py`, add at the top `from fonfon.models_setup import SdciDeployment` (next to the existing import) and replace the two `token` tests (added previously) — i.e. `test_step_result_token_defaults_none` and `test_step_result_token_roundtrips_in_dump` — with:
```python
def test_step_result_deployment_defaults_none():
    r = StepResult(title="x", status=SetupStatus.SKIPPED)
    assert r.deployment is None


def test_step_result_deployment_roundtrips_in_dump():
    r = StepResult(
        title="sdci config",
        status=SetupStatus.INSTALLED,
        deployment=SdciDeployment(
            base_dir="b", tasks_dir="t", uploads_dir="u", token="abc"
        ),
    )
    assert r.model_dump()["deployment"]["token"] == "abc"
```

In `tests/test_setup.py`, add `from fonfon.models_setup import SdciDeployment` and replace `test_run_step_propagates_token_from_step` + `test_run_step_token_none_for_plain_step` with:
```python
def test_run_step_propagates_deployment_from_step():
    class DeployStep(SetupStep):
        title = "T"

        def is_satisfied(self):
            return False

        def apply(self):
            self.deployment = SdciDeployment(
                base_dir="b", tasks_dir="t", uploads_dir="u", token="abc"
            )

    r = run_step(DeployStep())
    assert r.status is SetupStatus.INSTALLED
    assert r.deployment.token == "abc"


def test_run_step_deployment_none_for_plain_step():
    assert run_step(FakeStep("X")).deployment is None
```

In `tests/test_setup_steps.py`, replace `test_sdci_config_apply_configures_with_dirs_and_user` (from Task 4) with the deployment-asserting version:
```python
def test_sdci_config_apply_configures_and_sets_deployment():
    ts = FakeTailscale(ip="100.64.0.1")
    sdci = FakeSdci()
    step = SdciConfigStep(
        "preludian", PATHS, tailscale=ts, sdci=sdci, token_factory=lambda: "T" * 42
    )
    step.apply()
    assert sdci.setup_args == (
        "100.64.0.1", "T" * 42, PATHS.uploads, PATHS.tasks, "preludian",
    )
    assert step.deployment.base_dir == PATHS.base
    assert step.deployment.tasks_dir == PATHS.tasks
    assert step.deployment.uploads_dir == PATHS.uploads
    assert step.deployment.token == "T" * 42
```

In `tests/test_setup_output.py`, replace the `_report_with_token` helper and the three token/JSON tests added previously with:
```python
def _report_with_deployment():
    return SetupReport(
        steps=[
            StepResult(
                title="sdci config",
                status=SetupStatus.INSTALLED,
                detail="installed",
                deployment=SdciDeployment(
                    base_dir="/home/p/services/sdci",
                    tasks_dir="/home/p/services/sdci/tasks",
                    uploads_dir="/home/p/services/sdci/uploads",
                    token="T" * 42,
                ),
            ),
        ]
    )


def _render_summary(report):
    buf = StringIO()
    setup_console.render_summary(
        report, Console(file=buf, force_terminal=False, width=100)
    )
    return buf.getvalue()


def test_console_summary_renders_deployment_panel():
    out = _render_summary(_report_with_deployment())
    assert "sdci-server deployed" in out
    assert "/home/p/services/sdci/tasks" in out
    assert "/home/p/services/sdci/uploads" in out
    assert "T" * 42 in out


def test_console_summary_no_panel_without_deployment():
    out = _render_summary(_report())
    assert "sdci-server deployed" not in out


def test_json_includes_deployment_field():
    buf = StringIO()
    setup_json.render(
        _report_with_deployment(), Console(file=buf, force_terminal=False, width=100)
    )
    data = json_module.loads(buf.getvalue())
    assert data["steps"][0]["deployment"]["token"] == "T" * 42
```
Add `from fonfon.models_setup import SdciDeployment` to the imports at the top of `tests/test_setup_output.py`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_models_setup.py tests/test_setup.py tests/test_setup_steps.py tests/test_setup_output.py -v`
Expected: FAIL — no `SdciDeployment`; `StepResult`/`SetupStep` have no `deployment`; no panel.

- [ ] **Step 3: Implement.**

In `src/fonfon/models_setup.py`, add the model and swap the field:
```python
class SdciDeployment(BaseModel):
    base_dir: str
    tasks_dir: str
    uploads_dir: str
    token: str


class StepResult(BaseModel):
    title: str
    status: SetupStatus
    detail: str | None = None
    deployment: SdciDeployment | None = None
```

In `src/fonfon/services/setup_steps.py`: add `from fonfon.models_setup import SdciDeployment` to the imports; change the base-class attribute `token: str | None = None` to:
```python
    deployment: "SdciDeployment | None" = None  # set by steps that deploy a service
```
and change the last line of `SdciConfigStep.apply` from `self.token = token` to:
```python
        self.deployment = SdciDeployment(
            base_dir=self._paths.base,
            tasks_dir=self._paths.tasks,
            uploads_dir=self._paths.uploads,
            token=token,
        )
```

In `src/fonfon/services/setup.py::run_step`, change `token=step.token` to `deployment=step.deployment`:
```python
        return StepResult(
            title=step.title,
            status=SetupStatus.INSTALLED,
            detail="installed",
            deployment=step.deployment,
        )
```

In `src/fonfon/output/setup_console.py`: add imports at the top:
```python
from rich.panel import Panel
from rich.table import Table

from fonfon.models_setup import SdciDeployment
```
Replace the token tail of `render_summary` (the `token = next(...)` block) with a deployment panel, and add a helper:
```python
def _deployment_panel(deployment: SdciDeployment) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("project", deployment.base_dir)
    table.add_row("tasks", deployment.tasks_dir)
    table.add_row("uploads", deployment.uploads_dir)
    table.add_row("token", deployment.token)
    return Panel.fit(table, title="sdci-server deployed", border_style="green")


def render_summary(report: SetupReport, console: Console) -> None:
    """Print the counts footer and, if sdci was deployed, its deployment panel."""
    installed = sum(1 for s in report.steps if s.status is SetupStatus.INSTALLED)
    skipped = sum(1 for s in report.steps if s.status is SetupStatus.SKIPPED)
    failed = sum(1 for s in report.steps if s.status is SetupStatus.FAILED)
    console.print(
        f"[green]{installed} installed[/green] · "
        f"[dim]{skipped} skipped[/dim] · "
        f"[red]{failed} failed[/red]"
    )
    deployment = next((s.deployment for s in report.steps if s.deployment), None)
    if deployment:
        console.print(_deployment_panel(deployment))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_models_setup.py tests/test_setup.py tests/test_setup_steps.py tests/test_setup_output.py -v` → PASS. Then full suite `uv run pytest -q` → all green.

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/models_setup.py src/fonfon/services/setup_steps.py src/fonfon/services/setup.py src/fonfon/output/setup_console.py tests/test_models_setup.py tests/test_setup.py tests/test_setup_steps.py tests/test_setup_output.py
git commit -m "feat: surface a structured sdci deployment panel (project/tasks/uploads/token)"
```

---

### Task 6: `fonfon check` — sdci-server in Services

**Files:** Modify `src/fonfon/services/check.py`; Test `tests/test_check.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_check.py`:

```python
def test_services_list_includes_sdci_server():
    from fonfon.services.check import SERVICES

    assert "sdci-server" in SERVICES
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_check.py::test_services_list_includes_sdci_server -v`
Expected: FAIL — `"sdci-server"` not in `SERVICES`.

- [ ] **Step 3: Implement** in `src/fonfon/services/check.py`:

```python
SERVICES = ["docker", "ssh", "tailscaled", "sdci-server"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_check.py -v` → PASS (the generic Services rendering already handles the new entry).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/services/check.py tests/test_check.py
git commit -m "feat: report the sdci-server systemd unit in fonfon check services"
```

---

### Task 7: Documentation and version bump

**Files:** Modify `docs/manual/docs/commands/setup.md`, `docs/manual/docs/commands/check.md`, `pyproject.toml`, `uv.lock`

- [ ] **Step 1: Update `docs/manual/docs/commands/setup.md`.**

(a) In the "Provisioning steps" table, insert a new row for the dirs step immediately before the `Tailscale up` row (row 7), and renumber so the order is: … `6 sdci`, `7 Tailscale up`, `8 sdci dirs`, `9 sdci config`. Use these two replacement rows for 8 and 9:
```markdown
| 8 | **sdci dirs** | Creates `/home/<user>/services/sdci/{tasks,uploads}`, owned by the operator user, mode `0700` (skipped if they already exist) |
| 9 | **sdci config** | Generates a random 42-char token and runs `sdci-server setup --ip <ip> --token <token> --uploads-dir <…/uploads> --tasks-dir <…/tasks> --user <user>`, so the service runs as the operator user; stores config in `/etc/sdci/config` and registers its own systemd unit (skipped if `/etc/sdci/config` exists) |
```
(Update the existing `Tailscale up` row's number to `7` if it was numbered differently.)

(b) Replace the "The sdci token" section body so it documents the panel + deployment fields:
```markdown
## The sdci deployment

On a fresh configure, `fonfon setup` prints a panel summarising the sdci-server
deployment:

- **project** — `/home/<user>/services/sdci`
- **tasks** — `/home/<user>/services/sdci/tasks`
- **uploads** — `/home/<user>/services/sdci/uploads`
- **token** — the random 42-char token (generated with Python's `secrets`)

The token is also stored by `sdci-server` in `/etc/sdci/config`; fonfon keeps no
copy, so **record it when you see it**. The same fields appear under the
`deployment` object of the relevant step in `--output json`. On a re-run, if
`/etc/sdci/config` already exists the step is skipped and nothing is regenerated.
```

(c) In the "JSON output" section, replace the sentence describing entry fields with:
```markdown
The JSON payload contains a `steps` array, each entry with `title`, `status`
(`installed` \| `skipped` \| `failed`), an optional `detail` string, and an
optional `deployment` object (`base_dir`, `tasks_dir`, `uploads_dir`, `token`)
on the `sdci config` step.
```

- [ ] **Step 2: Update `docs/manual/docs/commands/check.md`.** Find where the checked systemd services are listed (the Services section) and add `sdci-server` to that list so the documented services read `docker`, `ssh`, `tailscaled`, and `sdci-server`. If the file does not enumerate services explicitly, add a sentence to the Services description: "The Services section also reports the `sdci-server` systemd unit." (Open the file first to match its exact wording.)

- [ ] **Step 3: Bump the version.** In `pyproject.toml`, change `version = "0.3.1"` to `version = "0.4.0"`, then `uv lock`.

- [ ] **Step 4: Full suite** — `uv run pytest -q` → all pass (~3 integration skip).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add docs/manual/docs/commands/setup.md docs/manual/docs/commands/check.md pyproject.toml uv.lock
git commit -m "docs: document sdci dirs + deploy panel + check service; bump to 0.4.0"
```

---

## Integration verification (manual, not a TDD task)

With a real key on a real VM:
```bash
TAILSCALE_AUTH_KEY=tskey-xxxx make debian-demo
```
Expect the install steps, `Tailscale up → 100.x`, `sdci dirs` creating the tree, then `sdci config` printing the **sdci-server deployed** panel (project/tasks/uploads/token). A second run reports `sdci dirs` and `sdci config` as `skipped`.

---

## Self-Review

**Spec coverage:**
- `/home/<user>/services/sdci/{tasks,uploads}` operator-owned `0700` → Tasks 1, 2, 3 (paths, Fs, dirs step). ✓
- Dirs step before sdci config → Task 4 (`build_steps` order: … Tailscale up, sdci dirs, sdci config). ✓
- `--uploads-dir`/`--tasks-dir`/`--user` on `sdci-server setup` → Task 4 (`Sdci.setup`, `SdciConfigStep`). ✓
- Rich deploy output (project/tasks/uploads/token) → Task 5 (panel + `SdciDeployment`). ✓
- JSON exposes the deployment → Task 5 (`deployment` field) + Task 7 docs. ✓
- sdci-client instructions → **dropped** (non-goal). ✓ (intentionally absent)
- sdci in `check` Services → Task 6. ✓
- Idempotency (dirs exist / `/etc/sdci/config` exists) → Tasks 3, 4 probes (unchanged config probe). ✓
- Manual + minor bump → Task 7 (`0.4.0`). ✓

**Placeholder scan:** none — every code/test step shows complete content. (Task 7 step 2 instructs reading `check.md` first because its exact wording isn't quoted here; the required end-state is explicit.)

**Type consistency:** `SdciPaths{base,tasks,uploads}` + `sdci_paths(user)`; `Fs.exists/make_dir(path,owner,mode)`; `SdciDirsStep(user, paths, fs=)`; `Sdci.setup(ip, token, uploads_dir, tasks_dir, user)`; `SdciConfigStep(user, paths, tailscale=, sdci=, token_factory=)`; `SdciDeployment{base_dir,tasks_dir,uploads_dir,token}`; `StepResult.deployment`; `SetupStep.deployment`. Titles `"sdci dirs"`/`"sdci config"` match between Tasks 3/4/5/7. The `token`→`deployment` migration is confined to Task 5 and updates every reader (run_step, console, StepResult, SetupStep) and its tests together.
