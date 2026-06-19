# `fonfon setup` Service Configuration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `fonfon setup <user>` with a required `--tailscale-auth-key` option and two new provisioning steps — join the Tailscale tailnet, then configure `sdci-server` against the tailnet IP with a generated token.

**Architecture:** Two new stateless `SetupStep`s appended to the existing six, backed by two new injectable boundary adapters (`Tailscale`, `Sdci`) and a `secrets`-based token helper. The sdci step re-derives the tailnet IP itself (no shared state). The generated token rides back on `StepResult.token` for the console summary and JSON. A pre-flight CLI gate rejects a missing key with a link, mirroring the existing root gate.

**Tech Stack:** Python 3.14, click, rich, pydantic; `secrets` stdlib; pytest with injected fake runners (`tests/fakes.py::completed`).

**Spec:** `docs/specs/2026-06-19-setup-services-design.md`

---

## File Structure

**New files:**
- `src/fonfon/services/token.py` — `generate_token(length=42)` (pure, no I/O).
- `src/fonfon/system/tailscale.py` — `Tailscale` adapter: `up(auth_key)`, `ipv4()`.
- `src/fonfon/system/sdci.py` — `Sdci` adapter: `setup(ip, token)`, `is_configured()`.
- `tests/test_token.py`, `tests/test_tailscale.py`, `tests/test_sdci.py`.

**Modified files:**
- `src/fonfon/models_setup.py` — add `token: str | None = None` to `StepResult`.
- `src/fonfon/services/setup_steps.py` — `SetupStep.token` class attr; new `TailscaleUpStep`, `SdciConfigStep`.
- `src/fonfon/services/setup.py` — `run_step` copies `step.token`; `build_steps`/`run_setup` thread `auth_key` and append the two steps.
- `src/fonfon/cli.py` — `--tailscale-auth-key` option (env fallback) + key gate + thread to `run_setup`.
- `src/fonfon/output/setup_console.py` — print the token in `render_summary`.
- `tools/debian-dev.sh` — `demo` passes `--tailscale-auth-key` from `$TAILSCALE_AUTH_KEY`.
- `docs/manual/docs/commands/setup.md` — document the option, the two steps, the token.
- `pyproject.toml` — bump `0.2.4 → 0.3.0` (new feature).
- Existing tests updated where signatures change: `tests/test_models_setup.py`, `tests/test_setup_steps.py`, `tests/test_setup.py`, `tests/test_cli_setup.py`, `tests/test_setup_output.py`.

**Conventions (from CLAUDE.md):** conventional commits; **no** "Co-authored-by Claude"; run `uv run pre-commit run --all-files` before each commit; tests via `uv run pytest`.

---

### Task 1: Token generator

**Files:**
- Create: `src/fonfon/services/token.py`
- Test: `tests/test_token.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_token.py
import string

from fonfon.services.token import generate_token


def test_generate_token_default_length():
    assert len(generate_token()) == 42


def test_generate_token_custom_length():
    assert len(generate_token(10)) == 10


def test_generate_token_is_alphanumeric():
    assert set(generate_token()) <= set(string.ascii_letters + string.digits)


def test_generate_token_varies_between_calls():
    assert generate_token() != generate_token()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_token.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.services.token'`.

- [ ] **Step 3: Implement**

```python
# src/fonfon/services/token.py
"""Generate a random alphanumeric token for service configuration."""

import secrets
import string

_ALPHABET = string.ascii_letters + string.digits


def generate_token(length: int = 42) -> str:
    """Return a cryptographically-random alphanumeric token of `length` chars."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_token.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/services/token.py tests/test_token.py
git commit -m "feat: add random alphanumeric token generator"
```

---

### Task 2: `Tailscale` boundary adapter

**Files:**
- Create: `src/fonfon/system/tailscale.py`
- Test: `tests/test_tailscale.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tailscale.py
from fonfon.system.tailscale import Tailscale
from tests.fakes import completed


def test_up_invokes_tailscale_up_with_auth_key():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    Tailscale(run=run).up("tskey-abc")
    assert seen["args"] == ["tailscale", "up", "--auth-key", "tskey-abc"]
    assert seen["timeout"] >= 60


def test_up_raises_on_failure():
    t = Tailscale(run=lambda args, timeout=10, env=None: completed(args, 1, "", "boom"))
    try:
        t.up("k")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "boom" in str(exc)


def test_ipv4_returns_first_address():
    t = Tailscale(run=lambda args, timeout=10, env=None: completed(args, 0, "100.64.0.1\n"))
    assert t.ipv4() == "100.64.0.1"


def test_ipv4_none_when_command_fails():
    t = Tailscale(run=lambda args, timeout=10, env=None: completed(args, 1, "", ""))
    assert t.ipv4() is None


def test_ipv4_none_when_output_empty():
    t = Tailscale(run=lambda args, timeout=10, env=None: completed(args, 0, "\n"))
    assert t.ipv4() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tailscale.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.system.tailscale'`.

- [ ] **Step 3: Implement**

```python
# src/fonfon/system/tailscale.py
"""Boundary adapter for the Tailscale CLI: join the tailnet and read its IP."""

from collections.abc import Callable

from fonfon.system._run import run as _default_run

TAILSCALE_UP_TIMEOUT = 60


class Tailscale:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def up(self, auth_key: str) -> None:
        proc = self._run(
            ["tailscale", "up", "--auth-key", auth_key],
            timeout=TAILSCALE_UP_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"tailscale up failed (rc {proc.returncode}): {detail}")

    def ipv4(self) -> str | None:
        proc = self._run(["tailscale", "ip", "-4"])
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_tailscale.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/system/tailscale.py tests/test_tailscale.py
git commit -m "feat: add Tailscale boundary adapter (up + ipv4)"
```

---

### Task 3: `Sdci` boundary adapter

**Files:**
- Create: `src/fonfon/system/sdci.py`
- Test: `tests/test_sdci.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sdci.py
from fonfon.system.sdci import Sdci
from tests.fakes import completed


def test_setup_invokes_sdci_server_setup():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    Sdci(run=run).setup("100.64.0.1", "tok")
    assert seen["args"] == [
        "sdci-server", "setup", "--ip", "100.64.0.1", "--token", "tok",
    ]
    assert seen["timeout"] >= 60


def test_setup_raises_on_failure():
    s = Sdci(run=lambda args, timeout=10, env=None: completed(args, 1, "", "nope"))
    try:
        s.setup("ip", "tok")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "nope" in str(exc)


def test_is_configured_true_when_config_present():
    s = Sdci(
        run=lambda *a, **k: completed([], 0),
        exists=lambda path: path == "/etc/sdci/config",
    )
    assert s.is_configured() is True


def test_is_configured_false_when_absent():
    s = Sdci(run=lambda *a, **k: completed([], 0), exists=lambda path: False)
    assert s.is_configured() is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sdci.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.system.sdci'`.

- [ ] **Step 3: Implement**

```python
# src/fonfon/system/sdci.py
"""Boundary adapter for sdci-server: configure it and detect prior config."""

import os
from collections.abc import Callable

from fonfon.system._run import run as _default_run

SDCI_CONFIG_PATH = "/etc/sdci/config"
SDCI_SETUP_TIMEOUT = 60


class Sdci:
    def __init__(
        self,
        run: Callable = _default_run,
        exists: Callable[[str], bool] = os.path.exists,
    ):
        self._run = run
        self._exists = exists

    def is_configured(self) -> bool:
        return self._exists(SDCI_CONFIG_PATH)

    def setup(self, ip: str, token: str) -> None:
        proc = self._run(
            ["sdci-server", "setup", "--ip", ip, "--token", token],
            timeout=SDCI_SETUP_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"sdci-server setup failed (rc {proc.returncode}): {detail}"
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_sdci.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/system/sdci.py tests/test_sdci.py
git commit -m "feat: add sdci-server boundary adapter (setup + is_configured)"
```

---

### Task 4: Token field on `StepResult` and `run_step` plumbing

**Files:**
- Modify: `src/fonfon/models_setup.py` (the `StepResult` model)
- Modify: `src/fonfon/services/setup_steps.py` (the `SetupStep` base class, lines 29-40)
- Modify: `src/fonfon/services/setup.py::run_step` (lines 34-46)
- Test: `tests/test_models_setup.py`, `tests/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models_setup.py`:

```python
def test_step_result_token_defaults_none():
    r = StepResult(title="x", status=SetupStatus.SKIPPED)
    assert r.token is None


def test_step_result_token_roundtrips_in_dump():
    r = StepResult(title="sdci config", status=SetupStatus.INSTALLED, token="abc123")
    assert r.model_dump()["token"] == "abc123"
```

Append to `tests/test_setup.py`:

```python
def test_run_step_propagates_token_from_step():
    class TokenStep(SetupStep):
        title = "T"

        def is_satisfied(self):
            return False

        def apply(self):
            self.token = "abc123"

    r = run_step(TokenStep())
    assert r.status is SetupStatus.INSTALLED
    assert r.token == "abc123"


def test_run_step_token_none_for_plain_step():
    r = run_step(FakeStep("X"))
    assert r.token is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_models_setup.py tests/test_setup.py -v`
Expected: FAIL — `StepResult` has no `token`; `SetupStep` has no `token` attribute / `StepResult(...).token` AttributeError.

- [ ] **Step 3: Implement**

In `src/fonfon/models_setup.py`, add the field to `StepResult`:

```python
class StepResult(BaseModel):
    title: str
    status: SetupStatus
    detail: str | None = None
    token: str | None = None
```

In `src/fonfon/services/setup_steps.py`, add a `token` class attribute to the base:

```python
class SetupStep(ABC):
    """Base class for an idempotent provisioning action."""

    title: str
    token: str | None = None  # steps that produce a secret expose it here

    @abstractmethod
    def is_satisfied(self) -> bool:
        """Return True if this step is already in the desired state."""

    @abstractmethod
    def apply(self) -> None:
        """Perform the mutation; raise on failure."""
```

In `src/fonfon/services/setup.py::run_step`, carry the token onto the INSTALLED result:

```python
def run_step(step: SetupStep) -> StepResult:
    """Apply the continue-on-error policy for a single step."""
    if step.is_satisfied():
        return StepResult(
            title=step.title, status=SetupStatus.SKIPPED, detail="already present"
        )
    try:
        step.apply()
        return StepResult(
            title=step.title,
            status=SetupStatus.INSTALLED,
            detail="installed",
            token=step.token,
        )
    except Exception as exc:  # noqa: BLE001 — continue-on-error by design
        return StepResult(title=step.title, status=SetupStatus.FAILED, detail=str(exc))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_models_setup.py tests/test_setup.py -v`
Expected: PASS (existing tests still green, new ones pass).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/models_setup.py src/fonfon/services/setup_steps.py src/fonfon/services/setup.py tests/test_models_setup.py tests/test_setup.py
git commit -m "feat: carry a generated token from a setup step to its result"
```

---

### Task 5: `TailscaleUpStep` and `SdciConfigStep`

**Files:**
- Modify: `src/fonfon/services/setup_steps.py` (add two classes + imports)
- Test: `tests/test_setup_steps.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_steps.py`:

```python
from fonfon.services.setup_steps import SdciConfigStep, TailscaleUpStep


class FakeTailscale:
    def __init__(self, ip=None):
        self._ip = ip
        self.upped_with = None

    def ipv4(self):
        return self._ip

    def up(self, auth_key):
        self.upped_with = auth_key
        self._ip = "100.64.0.1"


class FakeSdci:
    def __init__(self, configured=False):
        self._configured = configured
        self.setup_args = None

    def is_configured(self):
        return self._configured

    def setup(self, ip, token):
        self.setup_args = (ip, token)


def test_tailscale_up_satisfied_when_ip_present():
    step = TailscaleUpStep("k", tailscale=FakeTailscale(ip="100.64.0.1"))
    assert step.is_satisfied() is True


def test_tailscale_up_not_satisfied_without_ip():
    step = TailscaleUpStep("k", tailscale=FakeTailscale(ip=None))
    assert step.is_satisfied() is False


def test_tailscale_up_apply_calls_up_with_key():
    ts = FakeTailscale(ip=None)
    TailscaleUpStep("tskey-xyz", tailscale=ts).apply()
    assert ts.upped_with == "tskey-xyz"


def test_sdci_config_satisfied_when_configured():
    step = SdciConfigStep(
        tailscale=FakeTailscale(ip="100.64.0.1"), sdci=FakeSdci(configured=True)
    )
    assert step.is_satisfied() is True


def test_sdci_config_not_satisfied_when_unconfigured():
    step = SdciConfigStep(
        tailscale=FakeTailscale(ip="100.64.0.1"), sdci=FakeSdci(configured=False)
    )
    assert step.is_satisfied() is False


def test_sdci_config_apply_configures_with_ip_and_token():
    ts = FakeTailscale(ip="100.64.0.1")
    sdci = FakeSdci()
    step = SdciConfigStep(tailscale=ts, sdci=sdci, token_factory=lambda: "T" * 42)
    step.apply()
    assert sdci.setup_args == ("100.64.0.1", "T" * 42)
    assert step.token == "T" * 42


def test_sdci_config_apply_raises_without_ip():
    step = SdciConfigStep(
        tailscale=FakeTailscale(ip=None), sdci=FakeSdci(), token_factory=lambda: "T"
    )
    try:
        step.apply()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_setup_steps.py -v`
Expected: FAIL — `ImportError: cannot import name 'TailscaleUpStep'`.

- [ ] **Step 3: Implement**

In `src/fonfon/services/setup_steps.py`, add imports near the top (after the existing `from fonfon.system...` imports):

```python
from fonfon.services.token import generate_token
from fonfon.system.sdci import Sdci
from fonfon.system.tailscale import Tailscale
```

Append the two step classes at the end of the file:

```python
class TailscaleUpStep(SetupStep):
    """Join the tailnet with an auth key."""

    title = "Tailscale up"

    def __init__(self, auth_key: str, tailscale: Tailscale | None = None) -> None:
        self._auth_key = auth_key
        self._tailscale = tailscale or Tailscale()

    def is_satisfied(self) -> bool:
        return self._tailscale.ipv4() is not None

    def apply(self) -> None:
        self._tailscale.up(self._auth_key)


class SdciConfigStep(SetupStep):
    """Configure sdci-server against the tailnet IP with a generated token."""

    title = "sdci config"

    def __init__(
        self,
        tailscale: Tailscale | None = None,
        sdci: Sdci | None = None,
        token_factory: Callable[[], str] = generate_token,
    ) -> None:
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
        self._sdci.setup(ip, token)
        self.token = token
```

Note: `Callable` is already imported at the top of `setup_steps.py`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_setup_steps.py -v`
Expected: PASS (existing step tests still green, 7 new ones pass).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/services/setup_steps.py tests/test_setup_steps.py
git commit -m "feat: add Tailscale-up and sdci-config setup steps"
```

---

### Task 6: Thread `auth_key` through `build_steps` and `run_setup`

**Files:**
- Modify: `src/fonfon/services/setup.py` (`build_steps`, `run_setup`, imports)
- Test: `tests/test_setup.py` (update existing monkeypatch lambdas + add new test)

- [ ] **Step 1: Update existing tests and add the new one**

In `tests/test_setup.py`, the monkeypatched `build_steps` lambdas must accept the new positional `auth_key`. Replace the three occurrences of:

```python
    monkeypatch.setattr("fonfon.services.setup.build_steps", lambda u, run=None: steps)
```

with:

```python
    monkeypatch.setattr(
        "fonfon.services.setup.build_steps", lambda u, k=None, run=None: steps
    )
```

(They appear in `test_run_setup_calls_on_result_per_step`, `test_run_setup_calls_on_step_start_per_step`, and `test_run_setup_on_step_start_called_before_on_result`.)

Then add a new test:

```python
def test_build_steps_with_auth_key_appends_service_steps():
    titles = [s.title for s in build_steps("jon", "tskey-abc")]
    assert titles == [
        "User", "Docker", "Docker group", "Tailscale", "pipx", "sdci",
        "Tailscale up", "sdci config",
    ]


def test_build_steps_without_auth_key_is_install_only():
    titles = [s.title for s in build_steps("jon")]
    assert titles == ["User", "Docker", "Docker group", "Tailscale", "pipx", "sdci"]
```

(The existing `test_build_steps_order_and_titles` stays valid and overlaps the second new test — keep both; they are cheap.)

- [ ] **Step 2: Run to verify the new test fails**

Run: `uv run pytest tests/test_setup.py -v`
Expected: FAIL — `build_steps("jon", "tskey-abc")` raises `TypeError` (build_steps takes 1 positional arg) / the appended titles are absent.

- [ ] **Step 3: Implement**

In `src/fonfon/services/setup.py`, add imports:

```python
from fonfon.services.setup_steps import (
    DockerGroupStep,
    DockerStep,
    PipxStep,
    SdciConfigStep,
    SdciStep,
    SetupStep,
    TailscaleStep,
    TailscaleUpStep,
    UserStep,
)
from fonfon.system.sdci import Sdci
from fonfon.system.tailscale import Tailscale
```

(Add `SdciConfigStep`, `TailscaleUpStep` to the existing import block and the two new `system` imports.)

Replace `build_steps` and `run_setup`:

```python
def build_steps(
    new_user: str, auth_key: str | None = None, run: Callable = _default_run
) -> list[SetupStep]:
    """Return the provisioning steps in execution order.

    The two service-configuration steps are appended only when an auth key is
    supplied (the CLI requires one; calling without it yields install-only steps).
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
        steps.append(TailscaleUpStep(auth_key, tailscale=Tailscale(run=run)))
        steps.append(
            SdciConfigStep(tailscale=Tailscale(run=run), sdci=Sdci(run=run))
        )
    return steps


def run_setup(
    new_user: str,
    auth_key: str | None = None,
    *,
    run: Callable = _default_run,
    on_step_start: Callable[[SetupStep], None] | None = None,
    on_result: Callable[[StepResult], None] | None = None,
) -> SetupReport:
    """Run all provisioning steps and return the aggregated report."""
    results = []
    for step in build_steps(new_user, auth_key, run=run):
        if on_step_start is not None:
            on_step_start(step)
        result = run_step(step)
        if on_result is not None:
            on_result(result)
        results.append(result)
    return SetupReport(steps=results)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_setup.py -v`
Expected: PASS (all, including the two new tests).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/services/setup.py tests/test_setup.py
git commit -m "feat: append Tailscale-up and sdci-config steps when an auth key is given"
```

---

### Task 7: CLI `--tailscale-auth-key` option and key gate

**Files:**
- Modify: `src/fonfon/cli.py` (the `setup` command, lines 48-82)
- Test: `tests/test_cli_setup.py` (update existing patches + add missing-key test)

- [ ] **Step 1: Update existing tests and add the gate test**

Rewrite `tests/test_cli_setup.py` so the patched `run_setup` accepts the new positional `auth_key`, every successful invoke passes `--tailscale-auth-key`, and a new test covers the missing-key gate:

```python
"""Tests for the `fonfon setup` CLI command."""

import json as json_module

from click.testing import CliRunner

from fonfon.cli import main
from fonfon.models_setup import SetupReport, SetupStatus, StepResult

_KEY = ["--tailscale-auth-key", "tskey-test"]


def _ok_report():
    return SetupReport(steps=[StepResult(title="User", status=SetupStatus.SKIPPED)])


def _patch_run_setup(monkeypatch, report):
    monkeypatch.setattr(
        "fonfon.cli.run_setup",
        lambda u, k, run=None, on_step_start=None, on_result=None: report,
    )


def test_setup_requires_root(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 1000)
    result = CliRunner().invoke(main, ["setup", "jon", *_KEY])
    assert result.exit_code != 0
    assert "root" in result.output.lower()


def test_setup_requires_auth_key(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    called = {"ran": False}

    def _spy(*args, **kwargs):
        called["ran"] = True
        return _ok_report()

    monkeypatch.setattr("fonfon.cli.run_setup", _spy)
    result = CliRunner().invoke(
        main, ["setup", "jon"], env={"FONFON_TAILSCALE_AUTH_KEY": ""}
    )
    assert result.exit_code == 1
    assert "auth key" in result.output.lower()
    assert "login.tailscale.com" in result.output
    assert called["ran"] is False


def test_setup_runs_as_root_exit_zero(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    _patch_run_setup(monkeypatch, _ok_report())
    result = CliRunner().invoke(main, ["setup", "jon", *_KEY])
    assert result.exit_code == 0


def test_setup_exit_one_on_failure(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    failed = SetupReport(steps=[StepResult(title="Docker", status=SetupStatus.FAILED)])
    _patch_run_setup(monkeypatch, failed)
    result = CliRunner().invoke(main, ["setup", "jon", *_KEY])
    assert result.exit_code == 1


def test_setup_json(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    _patch_run_setup(monkeypatch, _ok_report())
    result = CliRunner().invoke(main, ["setup", "jon", "--output", "json", *_KEY])
    assert json_module.loads(result.output)["steps"][0]["status"] == "skipped"


def test_setup_accepts_key_from_env(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    _patch_run_setup(monkeypatch, _ok_report())
    result = CliRunner().invoke(
        main, ["setup", "jon"], env={"FONFON_TAILSCALE_AUTH_KEY": "tskey-env"}
    )
    assert result.exit_code == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: FAIL — the `--tailscale-auth-key` option doesn't exist yet (`no such option`), and the gate test finds no "auth key" message.

- [ ] **Step 3: Implement**

Replace the `setup` command in `src/fonfon/cli.py`:

```python
@main.command()
@click.argument("new_user")
@click.option(
    "--tailscale-auth-key",
    "tailscale_auth_key",
    envvar="FONFON_TAILSCALE_AUTH_KEY",
    default=None,
    help="Tailscale auth key to join the tailnet "
    "(or set FONFON_TAILSCALE_AUTH_KEY).",
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
    tailscale_auth_key: str | None,
    output_format: str,
) -> None:
    """Provision this server (Docker, Tailscale, pipx, sdci), join the tailnet,
    and configure sdci-server for an operator user."""
    if os.geteuid() != 0:
        Console().print("[red]fonfon setup must be run as root.[/red]")
        ctx.exit(1)
    if not tailscale_auth_key:
        console = Console()
        console.print("[red]fonfon setup requires a Tailscale auth key.[/red]")
        console.print(
            "Generate one at: "
            "https://login.tailscale.com/admin/settings/keys"
        )
        console.print(
            "Then re-run: fonfon setup <user> --tailscale-auth-key <key>"
        )
        ctx.exit(1)
    console = Console()
    if output_format == "json":
        report = run_setup(new_user, tailscale_auth_key)
        setup_json.render(report, console)
    else:
        setup_console.render_header(console)
        setup_console.render_action(console)

        def _runner(args, timeout=10, env=None):
            return run_streamed(args, console, timeout=timeout, env=env)

        report = run_setup(
            new_user,
            tailscale_auth_key,
            run=_runner,
            on_step_start=lambda step: setup_console.render_step_start(step, console),
            on_result=lambda r: setup_console.render_step(r, console),
        )
        setup_console.render_summary(report, console)
    ctx.exit(0 if report.ok else 1)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: PASS (all, including the gate and env tests).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/cli.py tests/test_cli_setup.py
git commit -m "feat: require a Tailscale auth key for fonfon setup"
```

---

### Task 8: Print the token in the console summary

**Files:**
- Modify: `src/fonfon/output/setup_console.py::render_summary` (lines 39-48)
- Test: `tests/test_setup_output.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_output.py`:

```python
def _report_with_token():
    return SetupReport(
        steps=[
            StepResult(
                title="sdci config",
                status=SetupStatus.INSTALLED,
                detail="installed",
                token="T" * 42,
            ),
        ]
    )


def _render_summary(report):
    buf = StringIO()
    setup_console.render_summary(
        report, Console(file=buf, force_terminal=False, width=100)
    )
    return buf.getvalue()


def test_console_summary_prints_token_when_present():
    out = _render_summary(_report_with_token())
    assert "sdci token" in out
    assert "T" * 42 in out


def test_console_summary_omits_token_when_absent():
    out = _render_summary(_report())
    assert "sdci token" not in out


def test_json_includes_token_field():
    buf = StringIO()
    setup_json.render(
        _report_with_token(), Console(file=buf, force_terminal=False, width=100)
    )
    data = json_module.loads(buf.getvalue())
    assert data["steps"][0]["token"] == "T" * 42
```

- [ ] **Step 2: Run to verify the console tests fail**

Run: `uv run pytest tests/test_setup_output.py -v`
Expected: FAIL — `test_console_summary_prints_token_when_present` (no "sdci token" in output). `test_json_includes_token_field` should already PASS (the model dumps the field).

- [ ] **Step 3: Implement**

In `src/fonfon/output/setup_console.py::render_summary`, append the token line after the counts footer:

```python
def render_summary(report: SetupReport, console: Console) -> None:
    """Print the counts footer and, if one was generated, the sdci token."""
    installed = sum(1 for s in report.steps if s.status is SetupStatus.INSTALLED)
    skipped = sum(1 for s in report.steps if s.status is SetupStatus.SKIPPED)
    failed = sum(1 for s in report.steps if s.status is SetupStatus.FAILED)
    console.print(
        f"[green]{installed} installed[/green] · "
        f"[dim]{skipped} skipped[/dim] · "
        f"[red]{failed} failed[/red]"
    )
    token = next((s.token for s in report.steps if s.token), None)
    if token:
        console.print(
            f"[bold]sdci token:[/bold] {token}  "
            f"[dim](stored in /etc/sdci/config)[/dim]"
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_setup_output.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
uv run pre-commit run --all-files
git add src/fonfon/output/setup_console.py tests/test_setup_output.py
git commit -m "feat: surface the generated sdci token in the setup summary"
```

---

### Task 9: Update `make debian-demo` to pass the auth key

**Files:**
- Modify: `tools/debian-dev.sh` (`cmd_demo`, around lines 122-145, and the header comment lines 9-11)

This task is shell glue with no unit test; verify with `bash -n` and a `make -n` dry run (the existing demo was validated the same way).

- [ ] **Step 1: Edit `cmd_demo`**

Replace the single setup invocation line:

```bash
  echo ">> Running 'fonfon setup ${DEMO_USER}' ..."
  limactl shell "${VM_NAME}" -- sudo "${SCIE_IN_VM}" setup "${DEMO_USER}"
```

with a key-aware block:

```bash
  echo ">> Running 'fonfon setup ${DEMO_USER}' ..."
  if [[ -n "${TAILSCALE_AUTH_KEY:-}" ]]; then
    limactl shell "${VM_NAME}" -- sudo "${SCIE_IN_VM}" \
      setup "${DEMO_USER}" --tailscale-auth-key "${TAILSCALE_AUTH_KEY}"
  else
    echo ">> No TAILSCALE_AUTH_KEY in env -- setup will stop at the required-key gate (demo)."
    limactl shell "${VM_NAME}" -- sudo "${SCIE_IN_VM}" setup "${DEMO_USER}" || true
  fi
```

- [ ] **Step 2: Update the header comment**

In the `demo` description comment block near the top (lines 9-11), change:

```bash
# `demo` runs a full end-to-end on a FRESH VM: build, recreate, install, then
# `fonfon check` followed by `fonfon setup preludian`.
```

to:

```bash
# `demo` runs a full end-to-end on a FRESH VM: build, recreate, install, then
# `fonfon check` followed by `fonfon setup preludian`. Set TAILSCALE_AUTH_KEY in
# the environment to also join the tailnet and configure sdci; without it the
# setup stops at the required-key gate.
```

- [ ] **Step 3: Verify syntax and dry-run**

Run:
```bash
bash -n tools/debian-dev.sh && echo "syntax OK"
make -n debian-demo
```
Expected: `syntax OK`; the dry run prints `ARCH=aarch64 bash tools/debian-dev.sh demo`.

- [ ] **Step 4: Commit**

```bash
uv run pre-commit run --all-files
git add tools/debian-dev.sh
git commit -m "chore: pass TAILSCALE_AUTH_KEY through the debian-demo setup run"
```

---

### Task 10: Documentation and version bump

**Files:**
- Modify: `docs/manual/docs/commands/setup.md`
- Modify: `pyproject.toml` (version), `uv.lock`

- [ ] **Step 1: Update the manual page**

In `docs/manual/docs/commands/setup.md`:

Update the opening paragraph (lines 3-7) to mention the new behaviour — replace it with:

```markdown
`fonfon setup` provisions a server from scratch. It creates an operator user,
installs Docker (via the official apt repository), adds the user to the Docker
group, installs Tailscale (via the official install script), installs pipx, and
installs sdci globally via pipx. With a Tailscale auth key it then **joins the
tailnet** and **configures `sdci-server`** against the tailnet IP. Each step is
**idempotent**: if the system already satisfies a step, it is skipped — so
`setup` is safe to re-run.
```

Add a new admonition after the "Must run as root" warning (after line 11):

```markdown
!!! warning "Requires a Tailscale auth key"
    `fonfon setup` requires `--tailscale-auth-key` (or the
    `FONFON_TAILSCALE_AUTH_KEY` environment variable). Without it, setup prints a
    link to the [Tailscale keys page](https://login.tailscale.com/admin/settings/keys)
    and exits non-zero **without making any changes**. Using the environment
    variable keeps the key out of your shell history.
```

Update the Usage block (lines 15-18) to:

```bash
sudo fonfon setup <new_user> --tailscale-auth-key <key>   # rich, colored (default)
sudo fonfon setup <new_user> --tailscale-auth-key <key> --output json
FONFON_TAILSCALE_AUTH_KEY=<key> sudo -E fonfon setup <new_user>   # key via env
```

Add two rows to the Provisioning steps table (after row 6 `sdci`):

```markdown
| 7 | **Tailscale up** | Joins the tailnet with `tailscale up --auth-key <key>`, yielding a `100.x` tailnet IPv4 (skipped if already connected) |
| 8 | **sdci config** | Generates a random 42-char token and runs `sdci-server setup --ip <tailnet-ip> --token <token>`; sdci-server stores config in `/etc/sdci/config` and registers its own systemd unit (skipped if `/etc/sdci/config` exists) |
```

Add a new section before "## sdci and `fonfon check`":

```markdown
## The sdci token

The token passed to `sdci-server setup` is generated by fonfon with Python's
`secrets` module (42 alphanumeric characters). It is printed once in the console
summary (`sdci token: …`) and stored by `sdci-server` in `/etc/sdci/config`.
**Copy it when you see it** — fonfon does not keep its own copy. On a re-run, if
`/etc/sdci/config` already exists the sdci step is skipped and no new token is
generated. The token also appears as the `token` field of the relevant entry in
`--output json`.
```

Update the "Exit code" table to add the missing-key row:

```markdown
| No Tailscale auth key provided | `1` |
```

- [ ] **Step 2: Bump the version**

In `pyproject.toml`, change `version = "0.2.4"` to `version = "0.3.0"`, then refresh the lock:

```bash
uv lock
```

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -q`
Expected: all pass (only the 3 integration tests skipped).

- [ ] **Step 4: Commit**

```bash
uv run pre-commit run --all-files
git add docs/manual/docs/commands/setup.md pyproject.toml uv.lock
git commit -m "docs: document setup service configuration; bump to 0.3.0"
```

---

## Integration verification (manual, not a TDD task)

After all tasks, the feature can be exercised end-to-end on a real VM with a real
key. This is **not** part of the automated suite (it needs a tailnet key and a
Lima VM):

```bash
TAILSCALE_AUTH_KEY=tskey-xxxx make debian-demo
```

Expect the install steps, then `Tailscale up → 100.x.y.z`, then `sdci config`
printing an `sdci token`. A second `sudo fonfon setup preludian --tailscale-auth-key …`
should report the two new steps as `skipped`.

---

## Self-Review

**Spec coverage:**
- Required `--tailscale-auth-key` + env fallback → Task 7. ✓
- Abort-early gate with link, no changes → Task 7 (`test_setup_requires_auth_key`). ✓
- Tailscale-up step (idempotent via `ipv4()`) → Tasks 2, 5. ✓
- sdci-config step (idempotent via `/etc/sdci/config`, re-derives IP, gen token) → Tasks 3, 5. ✓
- sdci-server self-registers systemd (fonfon just runs `setup`) → Task 3 (no unit file). ✓
- Token generated in fonfon, printed (console + json), persisted by sdci → Tasks 1, 4, 8. ✓
- Two independent stateless steps, no shared context → Task 5 (sdci re-derives IP). ✓
- Continue-on-error / `report.ok` exit code → unchanged `run_step`/`run_setup`; covered. ✓
- `make debian-demo` passes the key → Task 9. ✓
- Docs manual entry + minor version bump → Task 10. ✓

**Placeholder scan:** none — every code/test step shows complete content.

**Type consistency:** `Tailscale.up/ipv4`, `Sdci.setup/is_configured`, `generate_token`, `StepResult.token`, `SetupStep.token`, `TailscaleUpStep(auth_key, tailscale=)`, `SdciConfigStep(tailscale=, sdci=, token_factory=)`, `build_steps(new_user, auth_key=None, run=)`, `run_setup(new_user, auth_key=None, *, ...)` are used identically across tasks. Step titles `"Tailscale up"` / `"sdci config"` match between Tasks 5 and 6.
