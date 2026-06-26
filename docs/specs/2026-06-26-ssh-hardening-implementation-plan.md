# SSH hardening setup step — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two `SetupStep`s to `fonfon setup`, gated on a new `--github-user` flag, that (a) write the operator's `~/.ssh/authorized_keys` from a GitHub account's public keys and (b) harden `sshd` via a drop-in that disables root + password login and enables public-key auth — without restarting `sshd`, refusing to harden if it would lock the operator out, and advising a reload at the end.

**Architecture:** Follows the existing `setup` layering: small single-purpose `SetupStep`s (`is_satisfied()` probe + `apply()` mutation), all OS interaction behind injectable boundary adapters in `system/`, pure rendering in `services/ssh_config.py`, presentation DTOs in `models_setup.py`, rendering in `output/`. The two SSH steps run last in `build_steps`, in a top-level `if github_user:` block.

**Tech Stack:** Python 3.14, click, rich, pydantic. Tests: pytest. Docs: mkdocs-material. No new runtime dependencies (GitHub keys fetched with stdlib `urllib`, the same way `probes.public_ip` already does).

## Global Constraints

- The drop-in path is exactly `/etc/ssh/sshd_config.d/99-fonfon-hardening.conf`.
- The drop-in sets exactly: `PermitRootLogin no`, `PasswordAuthentication no`, `PubkeyAuthentication yes`, `KbdInteractiveAuthentication no`, `PermitEmptyPasswords no`, under a managed header.
- `authorized_keys` is overwritten with a fonfon-managed file (managed header + exactly the fetched keys), mode `0600`, owned by the operator; `~/.ssh` is mode `0700`, owned by the operator.
- Keys come from `https://github.com/<github_user>.keys`.
- The flag is `--github-user`, env var `FONFON_GITHUB_USER`.
- **Lockout safety:** the keys step raises (writing nothing) when the GitHub user has no public keys; the hardening step refuses (raises) when the operator has no `authorized_keys`.
- The hardening step does **not** restart or reload `sshd`; it sets a deployment that drives a reload advisory in the summary.
- Run `uv run pytest` and let the pre-commit git hook run on every commit. Use conventional-commit messages. Do NOT add "Co-authored-by".
- The final task bumps `pyproject.toml` `version` from `0.5.1` to `0.6.0` (one minor bump for the whole feature).

---

### Task 1: `ssh_paths` helper

**Files:**
- Create: `src/fonfon/services/ssh_paths.py`
- Test: `tests/test_ssh_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SshPaths` (pydantic `BaseModel` with str fields `ssh_dir`, `authorized_keys`); `ssh_paths(user: str) -> SshPaths`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ssh_paths.py
from fonfon.services.ssh_paths import ssh_paths


def test_ssh_paths_under_user_home():
    paths = ssh_paths("deploy")
    assert paths.ssh_dir == "/home/deploy/.ssh"
    assert paths.authorized_keys == "/home/deploy/.ssh/authorized_keys"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ssh_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fonfon.services.ssh_paths'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fonfon/services/ssh_paths.py
"""Derive the operator's SSH paths (.ssh dir + authorized_keys) from a username."""

from pydantic import BaseModel


class SshPaths(BaseModel):
    """Paths for the operator's SSH setup under their home directory."""

    ssh_dir: str
    authorized_keys: str


def ssh_paths(user: str) -> SshPaths:
    """Return the `.ssh` dir and `authorized_keys` path for `user`."""
    ssh_dir = f"/home/{user}/.ssh"
    return SshPaths(ssh_dir=ssh_dir, authorized_keys=f"{ssh_dir}/authorized_keys")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ssh_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/ssh_paths.py tests/test_ssh_paths.py
git commit -m "feat: add ssh_paths helper for the operator's .ssh paths"
```

---

### Task 2: `Fs.read_text`

**Files:**
- Modify: `src/fonfon/system/fs.py`
- Test: `tests/test_fs.py`

**Interfaces:**
- Consumes: the existing `Fs.__init__(run, exists, write_text)` signature.
- Produces: `Fs.__init__(..., read_text=None)` (new optional injected reader, default `lambda p: pathlib.Path(p).read_text()`); `Fs.read_text(path: str) -> str`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_fs.py`)

```python
def test_read_text_returns_file_contents():
    fs = Fs(read_text=lambda path: "data" if path == "/x" else "")
    assert fs.read_text("/x") == "data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fs.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'read_text'`

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/system/fs.py`

Add a module-level default reader beside `_default_write_text`:

```python
def _default_read_text(path: str) -> str:
    return pathlib.Path(path).read_text()
```

Add the `read_text` parameter to `__init__` (after `write_text`) and store it:

```python
    def __init__(
        self,
        run: Callable = _default_run,
        exists: Callable[[str], bool] = os.path.exists,
        write_text: Callable[[str, str], None] = _default_write_text,
        read_text: Callable[[str], str] = _default_read_text,
    ):
        self._run = run
        self._exists = exists
        self._write_text = write_text
        self._read_text = read_text
```

Add the method (next to `exists`):

```python
    def read_text(self, path: str) -> str:
        return self._read_text(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fs.py -v`
Expected: PASS (all pre-existing `Fs` tests still pass)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/system/fs.py tests/test_fs.py
git commit -m "feat: add Fs.read_text for content-equality probes"
```

---

### Task 3: `GitHubKeys` adapter

**Files:**
- Create: `src/fonfon/system/github_keys.py`
- Test: `tests/test_github_keys.py`

**Interfaces:**
- Consumes: stdlib `urllib.request` (injected opener `(url, timeout)`, like `probes.public_ip`).
- Produces: `GITHUB_KEYS_URL = "https://github.com/{username}.keys"`; `GitHubKeys(opener=_urlopen, timeout=GITHUB_KEYS_TIMEOUT)`; `GitHubKeys.fetch(username: str) -> list[str]` — returns the non-empty stripped key lines, raises `RuntimeError` on transport/HTTP error.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_github_keys.py
import pytest

from fonfon.system.github_keys import GITHUB_KEYS_URL, GitHubKeys


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_returns_key_lines():
    def opener(url, timeout):
        return _FakeResp(b"ssh-ed25519 AAA\nssh-rsa BBB\n")

    assert GitHubKeys(opener=opener).fetch("octocat") == [
        "ssh-ed25519 AAA",
        "ssh-rsa BBB",
    ]


def test_fetch_builds_user_keys_url():
    seen = {}

    def opener(url, timeout):
        seen["url"] = url
        return _FakeResp(b"ssh-ed25519 AAA\n")

    GitHubKeys(opener=opener).fetch("octocat")
    assert seen["url"] == GITHUB_KEYS_URL.format(username="octocat")
    assert seen["url"] == "https://github.com/octocat.keys"


def test_fetch_returns_empty_list_when_no_keys():
    def opener(url, timeout):
        return _FakeResp(b"")

    assert GitHubKeys(opener=opener).fetch("ghost") == []


def test_fetch_raises_on_network_error():
    def opener(url, timeout):
        raise OSError("404")

    with pytest.raises(RuntimeError, match="ghost"):
        GitHubKeys(opener=opener).fetch("ghost")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github_keys.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.system.github_keys'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fonfon/system/github_keys.py
"""Boundary adapter for fetching a GitHub user's public SSH keys.

Uses stdlib urllib behind an injectable opener (mirrors probes.public_ip), so it
needs no third-party HTTP dependency and runs inside the pex.
"""

import urllib.request
from collections.abc import Callable

GITHUB_KEYS_URL = "https://github.com/{username}.keys"
GITHUB_KEYS_TIMEOUT = 10


def _urlopen(url: str, timeout: int):
    return urllib.request.urlopen(url, timeout=timeout)


class GitHubKeys:
    def __init__(
        self, opener: Callable = _urlopen, timeout: int = GITHUB_KEYS_TIMEOUT
    ):
        self._opener = opener
        self._timeout = timeout

    def fetch(self, username: str) -> list[str]:
        """Return `username`'s public SSH keys (one per line); raise on failure.

        An existing user with no keys yields an empty list; a missing user (404)
        or any network error raises RuntimeError.
        """
        url = GITHUB_KEYS_URL.format(username=username)
        try:
            with self._opener(url, self._timeout) as resp:
                body = resp.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — surface any fetch failure uniformly
            raise RuntimeError(
                f"failed to fetch SSH keys for github user '{username}': {exc}"
            ) from exc
        return [line.strip() for line in body.splitlines() if line.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_keys.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/system/github_keys.py tests/test_github_keys.py
git commit -m "feat: add GitHubKeys adapter to fetch a user's public SSH keys"
```

---

### Task 4: `SshDeployment` model + widen the deployment union

**Files:**
- Modify: `src/fonfon/models_setup.py`
- Test: `tests/test_models_setup.py`

**Interfaces:**
- Consumes: the existing `SdciDeployment`, `TraefikDeployment`, `StepResult` models.
- Produces: `SshDeployment` (pydantic `BaseModel` with str fields `dropin_file`, `authorized_keys`, `github_user`, `reload_hint`); `StepResult.deployment: SdciDeployment | TraefikDeployment | SshDeployment | None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_models_setup.py`

Add `SshDeployment` to the existing top-of-file import (keep it at module top to avoid ruff `E402`):

```python
from fonfon.models_setup import (
    SdciDeployment,
    SetupReport,
    SetupStatus,
    SshDeployment,
    StepResult,
    TraefikDeployment,
)
```

Then append the two test functions:

```python
def test_ssh_deployment_fields():
    dep = SshDeployment(
        dropin_file="/etc/ssh/sshd_config.d/99-fonfon-hardening.conf",
        authorized_keys="/home/deploy/.ssh/authorized_keys",
        github_user="octocat",
        reload_hint="sudo systemctl reload ssh",
    )
    assert dep.github_user == "octocat"
    assert dep.dropin_file.endswith("99-fonfon-hardening.conf")


def test_step_result_accepts_ssh_deployment():
    dep = SshDeployment(
        dropin_file="d", authorized_keys="a", github_user="octocat", reload_hint="r"
    )
    result = StepResult(
        title="SSH hardening", status=SetupStatus.INSTALLED, deployment=dep
    )
    assert isinstance(result.deployment, SshDeployment)
    assert result.deployment.github_user == "octocat"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models_setup.py -v`
Expected: FAIL — `ImportError: cannot import name 'SshDeployment'`

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/models_setup.py`

Add after the `TraefikDeployment` class:

```python
class SshDeployment(BaseModel):
    dropin_file: str
    authorized_keys: str
    github_user: str
    reload_hint: str
```

Change `StepResult.deployment` from:

```python
    deployment: SdciDeployment | TraefikDeployment | None = None
```

to:

```python
    deployment: SdciDeployment | TraefikDeployment | SshDeployment | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_setup.py tests/test_setup_output.py -v`
Expected: PASS (the existing sdci/Traefik serialization tests still pass — the union keeps the concrete type)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/models_setup.py tests/test_models_setup.py
git commit -m "feat: add SshDeployment DTO and widen StepResult.deployment"
```

---

### Task 5: SSH config renderers

**Files:**
- Create: `src/fonfon/services/ssh_config.py`
- Test: `tests/test_ssh_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SSHD_DROPIN_DIR = "/etc/ssh/sshd_config.d"`, `SSHD_DROPIN_PATH = f"{SSHD_DROPIN_DIR}/99-fonfon-hardening.conf"`; `render_sshd_hardening() -> str`; `render_authorized_keys(github_user: str, keys: list[str]) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ssh_config.py
from fonfon.services.ssh_config import (
    SSHD_DROPIN_DIR,
    SSHD_DROPIN_PATH,
    render_authorized_keys,
    render_sshd_hardening,
)


def test_dropin_path_under_sshd_config_d():
    assert SSHD_DROPIN_DIR == "/etc/ssh/sshd_config.d"
    assert SSHD_DROPIN_PATH == "/etc/ssh/sshd_config.d/99-fonfon-hardening.conf"


def test_render_sshd_hardening_sets_all_directives():
    out = render_sshd_hardening()
    assert out.startswith("#")  # managed header first
    assert "PermitRootLogin no" in out
    assert "PasswordAuthentication no" in out
    assert "PubkeyAuthentication yes" in out
    assert "KbdInteractiveAuthentication no" in out
    assert "PermitEmptyPasswords no" in out


def test_render_authorized_keys_has_header_and_keys():
    out = render_authorized_keys("octocat", ["ssh-ed25519 AAA", "ssh-rsa BBB"])
    assert "github.com/octocat" in out
    assert "ssh-ed25519 AAA" in out
    assert "ssh-rsa BBB" in out
    assert out.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ssh_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonfon.services.ssh_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/fonfon/services/ssh_config.py
"""Pure renderers for the SSH hardening drop-in and authorized_keys file."""

SSHD_DROPIN_DIR = "/etc/ssh/sshd_config.d"
SSHD_DROPIN_PATH = f"{SSHD_DROPIN_DIR}/99-fonfon-hardening.conf"


def render_sshd_hardening() -> str:
    """Return fonfon's sshd hardening drop-in.

    Lands in /etc/ssh/sshd_config.d/, which Debian's stock sshd_config Includes,
    so these directives override the distro defaults. Disables root login and
    every password path (password + keyboard-interactive + empty) and enables
    public-key auth.
    """
    return """\
# Managed by fonfon — do not edit. Hardens SSH; see `fonfon setup --github-user`.
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
PermitEmptyPasswords no
"""


def render_authorized_keys(github_user: str, keys: list[str]) -> str:
    """Return a fonfon-managed authorized_keys file for the given GitHub keys."""
    header = f"# Managed by fonfon — keys from github.com/{github_user}.keys"
    return "\n".join([header, *keys]) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ssh_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/ssh_config.py tests/test_ssh_config.py
git commit -m "feat: add sshd-hardening and authorized_keys renderers"
```

---

### Task 6: SSH setup steps

**Files:**
- Modify: `src/fonfon/services/setup_steps.py`
- Test: `tests/test_setup_steps.py`

**Interfaces:**
- Consumes: `SshPaths`, `ssh_paths` (Task 1); `Fs.read_text`/`make_dir`/`write_file`/`exists` (Task 2 + existing); `GitHubKeys.fetch` (Task 3); `SshDeployment` (Task 4); `SSHD_DROPIN_DIR`/`SSHD_DROPIN_PATH`/`render_sshd_hardening`/`render_authorized_keys` (Task 5).
- Produces:
  - `AuthorizedKeysStep(user: str, github_user: str, paths: SshPaths, github: GitHubKeys | None = None, fs: Fs | None = None)` — title `"Authorized keys"`.
  - `SshHardeningStep(user: str, github_user: str, paths: SshPaths, fs: Fs | None = None)` — title `"SSH hardening"`; on apply sets `self.deployment: SshDeployment`.
  - Constants `SSH_DIR_MODE = "0700"`, `AUTHORIZED_KEYS_MODE = "0600"`, `SSHD_DROPIN_DIR_MODE = "0755"`, `SSHD_DROPIN_FILE_MODE = "0644"`, `SSH_RELOAD_HINT = "sudo systemctl reload ssh"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_setup_steps.py`

First, extend the imports at the **top** of the file (keep them at module top to avoid ruff `E402`). Add `AuthorizedKeysStep`, `SshHardeningStep` to the existing `from fonfon.services.setup_steps import (...)` block, and add two new import lines beneath it:

```python
from fonfon.services.ssh_config import SSHD_DROPIN_PATH, render_sshd_hardening
from fonfon.services.ssh_paths import ssh_paths
```

Then **modify the existing `FakeFs` class in place** (do not redefine it — that trips ruff `F811`). Add `contents` storage and a `read_text` method to the class already defined in the file:

```python
class FakeFs:
    def __init__(self, existing=(), contents=None):
        self._existing = set(existing) | set(contents or {})
        self.made = []
        self.writes = []
        self.contents = dict(contents or {})

    def exists(self, path):
        return path in self._existing

    def make_dir(self, path, owner, mode):
        self.made.append((path, owner, mode))
        self._existing.add(path)

    def write_file(self, path, content, owner, mode):
        self.writes.append((path, content, owner, mode))
        self._existing.add(path)
        self.contents[path] = content

    def read_text(self, path):
        return self.contents[path]
```

Finally, append a `FakeGitHubKeys`, an `SPATHS` constant, and the tests to the end of the file (no mid-file imports):

```python
# ── SSH steps ───────────────────────────────────────────────────────────────────


class FakeGitHubKeys:
    def __init__(self, keys=(), error=None):
        self._keys = list(keys)
        self._error = error
        self.fetched = []

    def fetch(self, username):
        self.fetched.append(username)
        if self._error is not None:
            raise self._error
        return list(self._keys)


SPATHS = ssh_paths("deploy")


def test_authorized_keys_satisfied_when_file_exists():
    fs = FakeFs(existing=(SPATHS.authorized_keys,))
    step = AuthorizedKeysStep("deploy", "octocat", SPATHS, fs=fs)
    assert step.is_satisfied() is True


def test_authorized_keys_not_satisfied_when_absent():
    step = AuthorizedKeysStep("deploy", "octocat", SPATHS, fs=FakeFs())
    assert step.is_satisfied() is False


def test_authorized_keys_apply_fetches_and_writes():
    fs = FakeFs()
    gh = FakeGitHubKeys(keys=["ssh-ed25519 AAA", "ssh-rsa BBB"])
    AuthorizedKeysStep("deploy", "octocat", SPATHS, github=gh, fs=fs).apply()

    assert gh.fetched == ["octocat"]
    # .ssh dir created 0700, owned by the operator
    assert (SPATHS.ssh_dir, "deploy", "0700") in fs.made
    # authorized_keys written 0600, owned by the operator, with both keys + header
    written = {path: (content, owner, mode) for path, content, owner, mode in fs.writes}
    assert SPATHS.authorized_keys in written
    content, owner, mode = written[SPATHS.authorized_keys]
    assert (owner, mode) == ("deploy", "0600")
    assert "ssh-ed25519 AAA" in content
    assert "ssh-rsa BBB" in content
    assert "github.com/octocat" in content


def test_authorized_keys_apply_raises_and_writes_nothing_when_no_keys():
    fs = FakeFs()
    step = AuthorizedKeysStep(
        "deploy", "ghost", SPATHS, github=FakeGitHubKeys(keys=[]), fs=fs
    )
    with pytest.raises(RuntimeError, match="no public SSH keys"):
        step.apply()
    assert fs.writes == []


def test_ssh_hardening_not_satisfied_when_dropin_absent():
    step = SshHardeningStep("deploy", "octocat", SPATHS, fs=FakeFs())
    assert step.is_satisfied() is False


def test_ssh_hardening_satisfied_when_content_matches():
    fs = FakeFs(contents={SSHD_DROPIN_PATH: render_sshd_hardening()})
    assert SshHardeningStep("deploy", "octocat", SPATHS, fs=fs).is_satisfied() is True


def test_ssh_hardening_not_satisfied_when_content_drifts():
    fs = FakeFs(contents={SSHD_DROPIN_PATH: "PermitRootLogin yes\n"})
    assert SshHardeningStep("deploy", "octocat", SPATHS, fs=fs).is_satisfied() is False


def test_ssh_hardening_apply_refuses_without_authorized_keys():
    # lockout guard: no authorized_keys present -> refuse, write nothing
    fs = FakeFs()
    step = SshHardeningStep("deploy", "octocat", SPATHS, fs=fs)
    with pytest.raises(RuntimeError, match="lock you out"):
        step.apply()
    assert fs.writes == []


def test_ssh_hardening_apply_writes_dropin_and_sets_deployment():
    fs = FakeFs(existing=(SPATHS.authorized_keys,))
    step = SshHardeningStep("deploy", "octocat", SPATHS, fs=fs)
    step.apply()

    written = {path: (content, owner, mode) for path, content, owner, mode in fs.writes}
    assert SSHD_DROPIN_PATH in written
    content, owner, mode = written[SSHD_DROPIN_PATH]
    assert (owner, mode) == ("root", "0644")
    assert content == render_sshd_hardening()
    # deployment surfaced for the reload advisory
    assert step.deployment.dropin_file == SSHD_DROPIN_PATH
    assert step.deployment.authorized_keys == SPATHS.authorized_keys
    assert step.deployment.github_user == "octocat"
    assert "reload" in step.deployment.reload_hint
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup_steps.py -v`
Expected: FAIL — `ImportError: cannot import name 'AuthorizedKeysStep' from 'fonfon.services.setup_steps'`

- [ ] **Step 3: Write minimal implementation** — in `src/fonfon/services/setup_steps.py`

Add to the imports at the top of the file (replace the existing `from fonfon.models_setup import SdciDeployment, TraefikDeployment` line with the 3-name version, and add the SSH imports):

```python
from fonfon.models_setup import SdciDeployment, SshDeployment, TraefikDeployment
from fonfon.services.ssh_config import (
    SSHD_DROPIN_DIR,
    SSHD_DROPIN_PATH,
    render_authorized_keys,
    render_sshd_hardening,
)
from fonfon.services.ssh_paths import SshPaths
from fonfon.system.github_keys import GitHubKeys
```

Widen the base-class attribute annotation:

```python
class SetupStep(ABC):
    """Base class for an idempotent provisioning action."""

    title: str
    deployment: SdciDeployment | TraefikDeployment | SshDeployment | None = None
```

Add the SSH constants near the other module constants:

```python
SSH_DIR_MODE = "0700"
AUTHORIZED_KEYS_MODE = "0600"
SSHD_DROPIN_DIR_MODE = "0755"
SSHD_DROPIN_FILE_MODE = "0644"
SSH_RELOAD_HINT = "sudo systemctl reload ssh"
```

Append the two step classes to the end of the file:

```python
class AuthorizedKeysStep(SetupStep):
    """Install the operator's authorized_keys from a GitHub user's public keys."""

    title = "Authorized keys"

    def __init__(
        self,
        user: str,
        github_user: str,
        paths: SshPaths,
        github: GitHubKeys | None = None,
        fs: Fs | None = None,
    ) -> None:
        self._user = user
        self._github_user = github_user
        self._paths = paths
        self._github = github or GitHubKeys()
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        return self._fs.exists(self._paths.authorized_keys)

    def apply(self) -> None:
        keys = self._github.fetch(self._github_user)
        if not keys:
            raise RuntimeError(
                f"github user '{self._github_user}' has no public SSH keys; "
                "refusing to write an empty authorized_keys"
            )
        self._fs.make_dir(self._paths.ssh_dir, self._user, SSH_DIR_MODE)
        self._fs.write_file(
            self._paths.authorized_keys,
            render_authorized_keys(self._github_user, keys),
            self._user,
            AUTHORIZED_KEYS_MODE,
        )


class SshHardeningStep(SetupStep):
    """Harden sshd via a drop-in; refuse if it would lock the operator out."""

    title = "SSH hardening"

    def __init__(
        self,
        user: str,
        github_user: str,
        paths: SshPaths,
        fs: Fs | None = None,
    ) -> None:
        self._user = user
        self._github_user = github_user
        self._paths = paths
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        if not self._fs.exists(SSHD_DROPIN_PATH):
            return False
        return self._fs.read_text(SSHD_DROPIN_PATH) == render_sshd_hardening()

    def apply(self) -> None:
        if not self._fs.exists(self._paths.authorized_keys):
            raise RuntimeError(
                f"refusing to harden SSH: {self._paths.authorized_keys} is "
                "missing; disabling password auth would lock you out. Ensure "
                "--github-user names an account with published SSH keys."
            )
        self._fs.make_dir(SSHD_DROPIN_DIR, "root", SSHD_DROPIN_DIR_MODE)
        self._fs.write_file(
            SSHD_DROPIN_PATH,
            render_sshd_hardening(),
            "root",
            SSHD_DROPIN_FILE_MODE,
        )
        self.deployment = SshDeployment(
            dropin_file=SSHD_DROPIN_PATH,
            authorized_keys=self._paths.authorized_keys,
            github_user=self._github_user,
            reload_hint=SSH_RELOAD_HINT,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup_steps.py -v`
Expected: PASS (all pre-existing setup-step tests still pass — `FakeFs` was extended, not redefined)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/services/setup_steps.py tests/test_setup_steps.py
git commit -m "feat: add authorized-keys and ssh-hardening setup steps"
```

---

### Task 7: Wire SSH steps into `build_steps` / `run_setup`

**Files:**
- Modify: `src/fonfon/services/setup.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `AuthorizedKeysStep`, `SshHardeningStep` (Task 6); `ssh_paths` (Task 1); `GitHubKeys` (Task 3); `Fs` (existing).
- Produces: `build_steps(new_user: str, auth_key: str | None = None, cert_email: str | None = None, github_user: str | None = None, run=_default_run) -> list[SetupStep]` — appends the two SSH steps last, only when `github_user` is truthy (independent of `auth_key`); `run_setup(new_user, auth_key=None, cert_email=None, github_user=None, *, run=..., on_step_start=None, on_result=None) -> SetupReport`.

- [ ] **Step 1: Write/adjust the failing tests** in `tests/test_setup.py`

Update the three `monkeypatch.setattr("fonfon.services.setup.build_steps", ...)` lambdas — change each `lambda u, k=None, c=None, run=None: steps` to add the `github_user` param:

```python
        "fonfon.services.setup.build_steps",
        lambda u, k=None, c=None, g=None, run=None: steps,
```

(There are three occurrences — in `test_run_setup_calls_on_result_per_step`, `test_run_setup_calls_on_step_start_per_step`, and `test_run_setup_on_step_start_called_before_on_result`.)

Then append the new coverage:

```python
def test_build_steps_with_github_user_appends_ssh_steps_last():
    titles = [s.title for s in build_steps("jon", "tskey-abc", None, "octocat")]
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
        "Authorized keys",
        "SSH hardening",
    ]


def test_build_steps_github_user_without_auth_key_still_hardens():
    # SSH hardening only needs the operator user, not the tailnet.
    titles = [s.title for s in build_steps("jon", None, None, "octocat")]
    assert titles == [
        "User",
        "Docker",
        "Docker group",
        "Tailscale",
        "pipx",
        "sdci",
        "Authorized keys",
        "SSH hardening",
    ]


def test_build_steps_without_github_user_has_no_ssh_steps():
    titles = [s.title for s in build_steps("jon", "tskey-abc")]
    assert "Authorized keys" not in titles
    assert "SSH hardening" not in titles


def test_build_steps_all_flags_order_ssh_after_traefik():
    titles = [
        s.title for s in build_steps("jon", "tskey-abc", "you@example.com", "octocat")
    ]
    assert titles[-2:] == ["Authorized keys", "SSH hardening"]
    assert "Traefik" in titles
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -v`
Expected: FAIL — `TypeError: build_steps() takes from 1 to 4 positional arguments but 4 were given` / the new tests cannot find the SSH titles.

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/services/setup.py`

Add `AuthorizedKeysStep`, `SshHardeningStep` to the `from fonfon.services.setup_steps import (...)` block, and add two imports:

```python
from fonfon.services.ssh_paths import ssh_paths
from fonfon.system.github_keys import GitHubKeys
```

Change the `build_steps` signature and append the SSH block **after** the `if auth_key:` block (before `return steps`):

```python
def build_steps(
    new_user: str,
    auth_key: str | None = None,
    cert_email: str | None = None,
    github_user: str | None = None,
    run: Callable = _default_run,
) -> list[SetupStep]:
    """Return the provisioning steps in execution order.

    The sdci steps are appended only when an auth key is supplied; the Traefik
    steps only when both an auth key and a cert email are supplied. The SSH
    hardening steps are appended last, only when a GitHub user is supplied
    (independent of the auth key — hardening needs only the operator account).
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
    if github_user:
        spaths = ssh_paths(new_user)
        steps.append(
            AuthorizedKeysStep(
                new_user, github_user, spaths, github=GitHubKeys(), fs=Fs(run=run)
            )
        )
        steps.append(SshHardeningStep(new_user, github_user, spaths, fs=Fs(run=run)))
    return steps
```

Change `run_setup` to accept and thread `github_user`:

```python
def run_setup(
    new_user: str,
    auth_key: str | None = None,
    cert_email: str | None = None,
    github_user: str | None = None,
    *,
    run: Callable = _default_run,
    on_step_start: Callable[[SetupStep], None] | None = None,
    on_result: Callable[[StepResult], None] | None = None,
) -> SetupReport:
    """Run all provisioning steps and return the aggregated report."""
    results = []
    for step in build_steps(new_user, auth_key, cert_email, github_user, run=run):
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
git commit -m "feat: wire SSH steps into build_steps behind --github-user"
```

---

### Task 8: CLI flag `--github-user`

**Files:**
- Modify: `src/fonfon/cli.py`
- Test: `tests/test_cli_setup.py`

**Interfaces:**
- Consumes: `run_setup(new_user, auth_key, cert_email, github_user, *, run, on_step_start, on_result)` (Task 7).
- Produces: `setup` command with a new option `--github-user` (env `FONFON_GITHUB_USER`, param `github_user`), passed positionally to `run_setup` (4th arg).

- [ ] **Step 1: Update the failing tests** in `tests/test_cli_setup.py`

Update `_patch_run_setup` and the two existing cert-email spies to accept the new `github_user` positional (`g=None`), so the cli passing it positionally doesn't collide with `run`:

```python
def _patch_run_setup(monkeypatch, report):
    monkeypatch.setattr(
        "fonfon.cli.run_setup",
        lambda u, k, c=None, g=None, run=None, on_step_start=None, on_result=None: report,
    )
```

In `test_setup_passes_cert_email_to_run_setup` and `test_setup_cert_email_from_env`, change each `_spy` signature to:

```python
    def _spy(u, k, c=None, g=None, run=None, on_step_start=None, on_result=None):
```

Then add two new tests:

```python
def test_setup_passes_github_user_to_run_setup(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    seen = {}

    def _spy(u, k, c=None, g=None, run=None, on_step_start=None, on_result=None):
        seen["github_user"] = g
        return _ok_report()

    monkeypatch.setattr("fonfon.cli.run_setup", _spy)
    result = CliRunner().invoke(
        main, ["setup", "jon", *_KEY, "--github-user", "octocat"]
    )
    assert result.exit_code == 0
    assert seen["github_user"] == "octocat"


def test_setup_github_user_from_env(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    seen = {}

    def _spy(u, k, c=None, g=None, run=None, on_step_start=None, on_result=None):
        seen["github_user"] = g
        return _ok_report()

    monkeypatch.setattr("fonfon.cli.run_setup", _spy)
    result = CliRunner().invoke(
        main, ["setup", "jon", *_KEY], env={"FONFON_GITHUB_USER": "envcat"}
    )
    assert result.exit_code == 0
    assert seen["github_user"] == "envcat"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: FAIL — the new tests fail because `setup` has no `--github-user` option (and `g` is never populated).

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/cli.py`

Add the option (after `--traefik-cert-email`, before `-o/--output`):

```python
@click.option(
    "--github-user",
    "github_user",
    envvar="FONFON_GITHUB_USER",
    default=None,
    help=(
        "GitHub username whose public SSH keys seed the operator's "
        "authorized_keys (or set FONFON_GITHUB_USER). Hardens SSH when set."
    ),
)
```

Add `github_user: str | None` to the `setup` signature (after `traefik_cert_email`), update the docstring to mention SSH hardening, and pass `github_user` positionally to **both** `run_setup` calls:

```python
def setup(
    ctx: click.Context,
    new_user: str,
    tailscale_key: str | None,
    traefik_cert_email: str | None,
    github_user: str | None,
    output_format: str,
) -> None:
    """Provision this server (Docker, Tailscale, pipx, sdci), join the tailnet,
    configure sdci-server, optionally deploy Traefik (--traefik-cert-email), and
    optionally harden SSH from a GitHub user's keys (--github-user)."""
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
        report = run_setup(new_user, tailscale_key, traefik_cert_email, github_user)
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
            github_user,
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
git commit -m "feat: add --github-user flag to fonfon setup"
```

---

### Task 9: SSH deployment panel + reload advisory in console output

**Files:**
- Modify: `src/fonfon/output/setup_console.py`
- Test: `tests/test_setup_output.py`

**Interfaces:**
- Consumes: `SshDeployment` (Task 4).
- Produces: `_ssh_panel(deployment: SshDeployment) -> Panel`; `render_summary` renders the SSH panel **and** a prominent reload advisory for any step carrying an `SshDeployment`.

- [ ] **Step 1: Write the failing tests** in `tests/test_setup_output.py`

Add `SshDeployment` to the existing top-of-file import (keep it at module top to avoid ruff `E402`):

```python
from fonfon.models_setup import (
    SdciDeployment,
    SetupReport,
    SetupStatus,
    SshDeployment,
    StepResult,
    TraefikDeployment,
)
```

Then append the test helper and functions:

```python
def _report_with_ssh():
    return SetupReport(
        steps=[
            StepResult(
                title="SSH hardening",
                status=SetupStatus.INSTALLED,
                detail="installed",
                deployment=SshDeployment(
                    dropin_file="/etc/ssh/sshd_config.d/99-fonfon-hardening.conf",
                    authorized_keys="/home/p/.ssh/authorized_keys",
                    github_user="octocat",
                    reload_hint="sudo systemctl reload ssh",
                ),
            ),
        ]
    )


def test_console_summary_renders_ssh_panel_and_reload_advice():
    out = _render_summary(_report_with_ssh())
    assert "SSH hardened" in out
    assert "octocat" in out
    assert "/home/p/.ssh/authorized_keys" in out
    assert "99-fonfon-hardening.conf" in out
    assert "Reload SSH" in out
    assert "systemctl reload ssh" in out


def test_console_summary_no_ssh_panel_without_deployment():
    out = _render_summary(_report())
    assert "SSH hardened" not in out
    assert "Reload SSH" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup_output.py -v`
Expected: FAIL — `AssertionError: 'SSH hardened' not in out` (the renderer ignores `SshDeployment`).

- [ ] **Step 3: Write minimal implementation** in `src/fonfon/output/setup_console.py`

Update the import to include `SshDeployment`:

```python
from fonfon.models_setup import (
    SdciDeployment,
    SetupReport,
    SetupStatus,
    SshDeployment,
    StepResult,
    TraefikDeployment,
)
```

Add the SSH panel builder after `_traefik_panel`:

```python
def _ssh_panel(deployment: SshDeployment) -> Panel:
    """Return a Panel summarising the SSH hardening result."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("github user", deployment.github_user)
    table.add_row("authorized_keys", deployment.authorized_keys)
    table.add_row("drop-in", deployment.dropin_file)
    return Panel.fit(table, title="SSH hardened", border_style="yellow")
```

Add an `SshDeployment` branch to the `render_summary` loop — print the panel **and** the reload advisory:

```python
    for step in report.steps:
        deployment = step.deployment
        if isinstance(deployment, SdciDeployment):
            console.print(_deployment_panel(deployment))
        elif isinstance(deployment, TraefikDeployment):
            console.print(_traefik_panel(deployment))
        elif isinstance(deployment, SshDeployment):
            console.print(_ssh_panel(deployment))
            console.print(
                f"[bold yellow]⚠ Reload SSH to apply: {deployment.reload_hint} "
                "(or reboot the server).[/bold yellow]"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup_output.py -v`
Expected: PASS (including the pre-existing sdci/Traefik panel tests)

- [ ] **Step 5: Commit**

```bash
git add src/fonfon/output/setup_console.py tests/test_setup_output.py
git commit -m "feat: render SSH hardening panel and reload advisory"
```

---

### Task 10: Documentation + version bump

**Files:**
- Modify: `docs/manual/docs/commands/setup.md`
- Modify: `pyproject.toml`
- Regenerate: `docs/manual/site/` (committed build output)

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: `--github-user` documented on the setup page; a new **SSH hardening** section; `version = "0.6.0"`.

- [ ] **Step 1: Run the full suite to confirm a green baseline**

Run: `uv run pytest`
Expected: PASS (all tests from Tasks 1–9).

- [ ] **Step 2: Update the setup command page**

In `docs/manual/docs/commands/setup.md`:

Under the Usage section (near the Traefik note), add:

```markdown
To also harden SSH — install the operator's `authorized_keys` from a GitHub
account and lock `sshd` down to key-only auth — pass `--github-user` (or set
`FONFON_GITHUB_USER`):

​```bash
sudo fonfon setup deploy --tailscale-key <key> --github-user your-gh-handle
​```
```

Append two rows to the provisioning-steps table:

```markdown
| 13 | **Authorized keys** | Fetches `https://github.com/<github-user>.keys` and writes `~/.ssh/authorized_keys` (mode `0600`, operator-owned) under a managed header (only when `--github-user` is set). **Fails, writing nothing, if that GitHub account has no public keys.** |
| 14 | **SSH hardening** | Writes `/etc/ssh/sshd_config.d/99-fonfon-hardening.conf` (`PermitRootLogin no`, `PasswordAuthentication no`, `PubkeyAuthentication yes`, `KbdInteractiveAuthentication no`, `PermitEmptyPasswords no`). **Refuses if the operator has no `authorized_keys`** (lockout guard). Does **not** restart `sshd` — advises a reload. |
```

Add a new section after "The sdci deployment" (or before the "Debian-family only" note):

````markdown
## SSH hardening

Pass `--github-user <account>` (or set `FONFON_GITHUB_USER`) to harden SSH. Two
steps run last:

1. **Authorized keys** — fonfon fetches the account's public keys from
   `https://github.com/<account>.keys` and writes them to the operator's
   `~/.ssh/authorized_keys` (mode `0600`, owned by the operator) under a
   `# Managed by fonfon` header. The file is **overwritten** to match GitHub.
2. **SSH hardening** — fonfon writes a drop-in at
   `/etc/ssh/sshd_config.d/99-fonfon-hardening.conf` (which Debian's stock
   `sshd_config` already `Include`s):

   ```text
   PermitRootLogin no
   PasswordAuthentication no
   PubkeyAuthentication yes
   KbdInteractiveAuthentication no
   PermitEmptyPasswords no
   ```

!!! danger "Reload SSH afterwards"
    fonfon does **not** restart or reload `sshd` — changing live SSH policy
    mid-session is risky. After setup, **reload SSH for the new policy to take
    effect**:

    ```bash
    sudo systemctl reload ssh   # or reboot the server
    ```

    Keep your current session open and verify key-based login in a **new**
    terminal before closing it.

!!! warning "Lockout safety"
    Because hardening disables password login, fonfon will not strand you:

    - The **Authorized keys** step fails (writing nothing) if the GitHub account
      has no published keys.
    - The **SSH hardening** step refuses to run unless the operator already has a
      populated `~/.ssh/authorized_keys`.

    So if no usable key is available, password authentication is left enabled and
    the run exits non-zero with a clear message.

!!! note "Re-running"
    The **Authorized keys** step is satisfied once the file exists, so a re-run
    does **not** re-sync from GitHub; delete `~/.ssh/authorized_keys` and re-run
    to force a refresh. The **SSH hardening** step self-heals: if the drop-in's
    content drifts, a re-run rewrites it.
````

Also update the **JSON output** section's sentence about the `deployment` object to note it may be an sdci, Traefik, **or SSH** (`dropin_file`, `authorized_keys`, `github_user`, `reload_hint`) deployment.

- [ ] **Step 3: Bump the version**

In `pyproject.toml`, change `version = "0.5.1"` to `version = "0.6.0"`.

- [ ] **Step 4: Rebuild the committed docs site**

Run: `uv run mkdocs build -f docs/manual/mkdocs.yml`
Expected: builds into `docs/manual/site/` with no errors. (A missing-page/nav warning means a path is wrong — fix it. The red "MkDocs 2.0" upstream advisory line is not an error.)

- [ ] **Step 5: Commit**

```bash
git add docs/manual/docs/commands/setup.md docs/manual/site pyproject.toml
git commit -m "docs: document SSH hardening (--github-user); bump to 0.6.0"
```

---

## Final verification

- [ ] **Run the full unit suite:** `uv run pytest` → all green.
- [ ] **Run the linters/hooks:** `uv run pre-commit run --all-files` → all pass (ruff format + lint clean).
- [ ] **Sanity-check the CLI help:** `uv run fonfon setup --help` → shows `--github-user` alongside `--tailscale-key` and `--traefik-cert-email`.
- [ ] **Optional end-to-end:** on a Debian VM (`make debian-demo` then `make debian-deploy`, or `make test-integration`), run `sudo fonfon setup deploy --tailscale-key <key> --github-user <real-gh-handle>` and confirm: `~deploy/.ssh/authorized_keys` contains the GitHub keys (mode `0600`); `/etc/ssh/sshd_config.d/99-fonfon-hardening.conf` exists; `sudo sshd -T | grep -E 'permitrootlogin|passwordauthentication|pubkeyauthentication'` reflects the drop-in **after** `systemctl reload ssh`; the summary printed the reload advisory.

## Self-review notes (author)

- **Spec coverage:** `--github-user` flag (Task 8), GitHub key fetch (Task 3), authorized_keys write `0600`/managed (Tasks 5/6), `~/.ssh` `0700` (Task 6), drop-in with all five directives (Tasks 5/6), no service restart + reload advisory (Tasks 6/9), lockout guard both layers (Task 6), gating + last-place ordering (Task 7), models/output (Tasks 4/9), docs + `0.6.0` bump (Task 10) — all mapped.
- **Type consistency:** `github_user` is the parameter name through `AuthorizedKeysStep`, `SshHardeningStep`, `build_steps`, `run_setup`; the CLI option param is `github_user` passed positionally (4th arg). `SshPaths` fields (`ssh_dir`, `authorized_keys`) are used identically in Tasks 1, 6. `SshDeployment` fields (`dropin_file`, `authorized_keys`, `github_user`, `reload_hint`) match across Tasks 4, 6, 9.
- **Green-between-tasks:** Task 7 changes `run_setup`/`build_steps` signatures but the cli still calls `run_setup` with 3 positionals (unchanged until Task 8) → `github_user` defaults `None` → suite green; the cli test spies are substitutes and unaffected until updated in Task 8.
- **`FakeFs` is modified in place** (Task 6) to add `contents`/`read_text`, not redefined (avoids ruff `F811`); the new `contents` kwarg defaults `None`, so the pre-existing sdci/Traefik step tests are unaffected.
- **Ordering rationale:** SSH steps run last so `ca-certificates` (installed by `DockerStep`) is present for the HTTPS fetch, and so the reload advisory is the final thing printed. This keeps the change append-only — existing step-order assertions (which never pass `github_user`) stay valid.
- **Known limitation** (authorized_keys not re-synced on re-run) is intentional, mirrors the Traefik precedent, and is documented (Task 10).
