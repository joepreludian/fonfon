# `fonfon setup <new_user>` — Design

- **Date:** 2026-06-19
- **Status:** Approved (design); not yet implemented
- **Topic:** A root-only provisioning command that installs the base stack
  (Docker, Tailscale, pipx, sdci) and prepares an operator user — the mutating
  counterpart to `fonfon check`.

## Context & motivation

`fonfon check` reports what a server has. `fonfon setup` makes it so: it takes a
fresh Debian box to the desired baseline. It is the first **mutating** command,
so it establishes the action/installer layer that future provisioning commands
(SSH hardening, service config) will reuse.

It is designed to be safe to re-run: every action is idempotent (it checks
before it acts, reusing `check`'s read-only probes) and the command continues
past a failed step, reporting per-step results.

## Goals

- `fonfon setup <new_user>`: create the operator user, install Docker, Tailscale,
  pipx, and sdci, idempotently and with a clear per-step report.
- Establish the mutating "action" layer (Step abstraction + mutating adapters)
  as the counterpart to the read-only probes.
- Extend `check` to validate sdci via a new pip/pipx check method.

## Non-goals

- Joining a Tailscale tailnet (needs an auth key; later).
- SSH hardening / service configuration (separate future commands).
- Non-Debian support (package steps assume apt/dpkg; consistent with `check`).
- A `--dry-run` mode (YAGNI now; the idempotency probes already make re-runs safe).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| `<new_user>` role | Create if missing; add to `sudo` and `docker` | Gives a non-root operator with docker access post-setup. |
| Docker install | Official **apt repository** method | Auditable, pinned to Docker's repo, the documented production path. |
| Tailscale install | Official **install script** (`install.sh`) | The method tailscale.com recommends; detects distro, adds the repo. |
| Re-run / errors | **Idempotent + continue-on-error** | Skip satisfied steps; attempt all; report per-step; exit non-zero if any failed. |
| Step structure | **`SetupStep` abstraction** | Each action is check + act; uniform reporting, independent tests, easy to extend. |
| sdci install scope | **Global pipx** (`PIPX_HOME=/opt/pipx`, `PIPX_BIN_DIR=/usr/local/bin`) | On `PATH` for all users incl. `<new_user>`; checkable by `check` without a per-user context. Works on Debian 12's pipx 1.1 (no `--global` flag). |
| Output | `SetupStatus` + console/json renderers | Mirrors `check`; json for automation. |

## Architecture

### The `SetupStep` abstraction

```python
class SetupStatus(StrEnum):
    INSTALLED = "installed"   # apply() ran and succeeded
    SKIPPED = "skipped"       # already satisfied
    FAILED = "failed"         # apply() raised

class SetupStep(ABC):
    title: str
    @abstractmethod
    def is_satisfied(self) -> bool: ...   # idempotency probe (read-only)
    @abstractmethod
    def apply(self) -> None: ...          # the mutation; raises on failure


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

Each concrete step is constructed with its (injectable) adapters, so tests drive
it with fakes. Steps reuse the read-only adapters (`Dpkg`, `Users`, `Pipx`) for
`is_satisfied` and the mutating adapters for `apply`.

### The use-case: `run_setup`

```python
def run_setup(new_user: str) -> SetupReport:
    steps = build_steps(new_user)           # ordered list of SetupStep
    results = []
    for step in steps:
        results.append(run_step(step))      # satisfied->SKIPPED; apply ok->INSTALLED; raise->FAILED
    return SetupReport(steps=results)
```

`run_step` is the policy: `is_satisfied()` → `SKIPPED`; else `try: apply()` →
`INSTALLED`, `except Exception as e:` → `FAILED` with the message (continue-on-error).

### CLI

`fonfon setup <new_user> [-o/--output console|json]`:

1. **Root gate first** — `os.geteuid() != 0` → print a clear error, `ctx.exit(1)`,
   take no action.
2. `report = run_setup(new_user)`, render via the chosen renderer.
3. `ctx.exit(0 if report.ok else 1)`.

## Steps (ordered)

| # | Step | `is_satisfied()` | `apply()` |
|---|------|------------------|-----------|
| 1 | **User** | `Users.exists(u)` and `Users.in_group(u, "sudo")` | `Users.create(u)` if missing (`useradd -m -s /bin/bash`); `Users.add_to_group(u, "sudo")` |
| 2 | **Docker** | `Dpkg.query("docker-ce").installed` | apt-repo flow (below) |
| 3 | **Docker group** | `Users.in_group(u, "docker")` | `Users.add_to_group(u, "docker")` (runs after step 2 creates the group) |
| 4 | **Tailscale** | `Dpkg.query("tailscale").installed` | run `https://tailscale.com/install.sh` via `sh` |
| 5 | **pipx** | `Dpkg.query("python3-pipx").installed` | `Apt.install("python3-pipx")` |
| 6 | **sdci** | `Pipx.is_installed("sdci")` | `Pipx.install_global("sdci")` |

**Docker apt-repo flow (step 2 `apply`):**
1. `Apt.install("ca-certificates", "curl")`
2. `Apt.add_keyring("https://download.docker.com/linux/debian/gpg", "/etc/apt/keyrings/docker.asc")`
   — `install -m 0755 -d /etc/apt/keyrings`, `curl -fsSL <url> -o <dest>`, `chmod a+r <dest>`
3. `Apt.add_repo(<deb line>, "/etc/apt/sources.list.d/docker.list")`
   — line: `deb [arch=<dpkg --print-architecture> signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian <VERSION_CODENAME> stable`
4. `Apt.update()`
5. `Apt.install("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin")`

The codename comes from `read_os_release()["VERSION_CODENAME"]`; the arch from
`dpkg --print-architecture`.

## Mutating boundary adapters (`system/`, injectable `run` seam)

- **`Apt`** — `update()`, `install(*pkgs)` (with `DEBIAN_FRONTEND=noninteractive -y`),
  `add_keyring(url, dest)`, `add_repo(content, dest)`.
- **`Users`** — `exists(u)` (`id -u`), `create(u)` (`useradd -m -s /bin/bash`),
  `in_group(u, g)` (`id -nG`), `add_to_group(u, g)` (`usermod -aG`), `group_exists(g)`.
- **`Pipx`** — `install_global(pkg)` (`pipx install` with `PIPX_HOME`/`PIPX_BIN_DIR`
  env), `is_installed(pkg)` (`pipx list --short` against the global `PIPX_HOME`,
  parse package names). Missing `pipx` binary → `is_installed` returns False.

All run through the existing `system/_run.py` runner (which already swallows
`FileNotFoundError`/`TimeoutExpired`), so adapters are unit-testable with fakes.

## Output

`SetupStatus` style map: `INSTALLED` green (`✓`), `SKIPPED` dim (`–`), `FAILED`
red (`✗`). The console renderer reuses the `build_header` logo and prints each
step's result row plus a summary footer (`n installed · n skipped · n failed`).
`--output json` prints `report.model_dump_json()`. Exit code from `report.ok`.

To keep installs legible, the console renderer prints each step result as it
completes (the use-case yields results incrementally) rather than only at the end.

## `check` extension (sdci via pipx)

- New boundary method **`Pipx.is_installed(pkg)`** — the "another method to check
  pip packages", distinct from `Dpkg`.
- `check`'s **Packages** section gains an **`sdci`** item validated via `Pipx`
  (`OK` if present, else `FAIL`), alongside the dpkg-checked `sudo` / `docker-ce`
  / `tailscale` / `python3-pipx`.

## Testing strategy (TDD)

| Layer | How |
|---|---|
| Mutating adapters (`Apt`, `Users`, `Pipx`) | Fake `run`; assert the argv issued and the parsing (`Users.in_group`, `Pipx.is_installed`). |
| Each `SetupStep` | Inject fake adapters: satisfied → `is_satisfied` True; unsatisfied + `apply` ok; `apply` raises. |
| `run_step` / `run_setup` policy | Crafted steps → SKIPPED / INSTALLED / FAILED; continue-on-error; `report.ok` gate. |
| Renderers | Recording `Console` substring asserts; json round-trips. |
| CLI | `CliRunner` + patched `os.geteuid` (root vs non-root exit codes); stubbed `run_setup`. |
| `check` sdci item | Fake `Pipx` → sdci OK/FAIL in the Packages section. |
| Integration | Lima: `sudo fonfon setup <u>` on real Debian — asserts it runs and (best-effort) installs; at minimum a second run reports SKIPPED. |

## Security note

Tailscale's `install.sh` (piped to `sh`) and Docker's GPG `curl` are the official
vendor methods chosen above, fetched over HTTPS; Docker uses the keyring + pinned
repo. These run only under the root gate.

## Open items / future

- Tailscale tailnet join (ephemeral auth key) — later.
- Other distros: add an `Apt`-equivalent + package-name mapping behind a strategy,
  mirroring `check`'s `PackageBackend`.
- A `--dry-run` preview if it proves useful.
