# sdci service directories + richer deploy output; sdci in `check` services — Design

- **Date:** 2026-06-20
- **Status:** Approved (design); not yet implemented
- **Topic:** Extend `fonfon setup` to create the operator's sdci service-directory
  tree and point `sdci-server setup` at it, surface a richer deploy summary
  (project/tasks/uploads dirs + token), and add the `sdci-server` systemd unit to
  the `fonfon check` Services section.

## Context & motivation

`fonfon setup` currently installs sdci, joins the tailnet, and runs
`sdci-server setup --ip <ip> --token <token>`, surfacing just the generated
token. It does not provision the directories sdci-server needs for tasks and
uploads, and `fonfon check` only reports sdci as an installed package — not
whether its service is running.

This change provisions a per-operator service-directory tree, passes it to
`sdci-server setup`, reports the full deployment (locations + token) in a rich
panel, and teaches `check` to report the `sdci-server` systemd unit. It builds
directly on the just-shipped service-configuration feature (see
`docs/specs/2026-06-19-setup-services-design.md`).

## Goals

- Create `/home/<user>/services/sdci/{tasks,uploads}` (operator-owned, `0700`)
  as a new idempotent setup step, before the sdci config step.
- Pass `--uploads-dir`, `--tasks-dir`, and `--user <operator>` to
  `sdci-server setup` so the service runs as the unprivileged operator user.
- Replace the flat token surfacing with a structured `SdciDeployment`
  (base/tasks/uploads dirs + token), rendered as a rich panel (console) and
  nested under `deployment` (JSON).
- Add `sdci-server` to the `fonfon check` Services (systemd) list, keeping the
  existing Packages `sdci` executable check.

## Non-goals

- Printing sdci-client connection instructions (explicitly dropped).
- Making the service tree path configurable via a flag (YAGNI; derived from the
  operator username).
- Deriving the home directory dynamically (e.g. `getent passwd`) — `useradd -m`
  yields `/home/<user>`, which we assume.
- Non-Debian support; SSH hardening (out of scope, as before).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Directory ownership / mode | **operator user, `0700`** | Lives in the user's home; private. Root (and the operator) retain access regardless of who sdci-server runs as. |
| Directory creation | `install -d -o <user> -g <user> -m 0700 <path>` | Single idempotent command that sets owner+group+mode atomically; creates parents. |
| Path source | derived from username: `/home/<user>/services/sdci/...` | Matches `useradd -m`; no extra config surface. |
| Step structure | a **separate "sdci dirs" step** before "sdci config" | Per-step ✓/✗ reporting; matches the existing one-concern-per-step model. |
| Deploy data | **consolidated `SdciDeployment` model** carried on `StepResult.deployment` (replaces the flat `token`) | Cohesive bundle; one structured field beats four sdci-specific scalars on a generic DTO. JSON `token`→`deployment` shape change is acceptable (same feature area, pre-1.0). |
| Console output | a **rich panel** listing project/tasks/uploads/token on a fresh deploy | The requested "rich format" surfacing; omitted on idempotent skip. |
| sdci runtime user | `sdci-server setup --user <operator>` | Runs the sdci-server systemd unit as the unprivileged operator user, not root — least privilege; aligns with the `0700` operator-owned dirs (the service reads/writes its own tree). |
| `check` sdci | add **`sdci-server`** to the systemd Services list; **keep** the Packages `sdci` executable item | "Installed" and "running" are different questions; both are useful. |

## Architecture

Additive, reusing the `SetupStep` / `run_step` / `run_setup` machinery and the
injectable-runner adapter pattern.

### Shared path helper

```python
# src/fonfon/services/sdci_paths.py
class SdciPaths(BaseModel):
    base: str      # /home/<user>/services/sdci
    tasks: str     # <base>/tasks
    uploads: str   # <base>/uploads

def sdci_paths(user: str) -> SdciPaths:
    base = f"/home/{user}/services/sdci"
    return SdciPaths(base=base, tasks=f"{base}/tasks", uploads=f"{base}/uploads")
```

Used by both the dirs step and the config step so they agree on locations.

### New boundary adapter `Fs` (`system/fs.py`, injectable `run`/`exists`)

- `exists(path) -> bool` — defaults to `os.path.exists` (injectable, like `Sdci`).
- `make_dir(path, owner, mode) -> None` — runs
  `["install", "-d", "-o", owner, "-g", owner, "-m", mode, path]`; raises
  `RuntimeError` on non-zero rc (house pattern: `stderr.strip() or stdout.strip()`).

### New step `SdciDirsStep`

| | Behaviour |
|---|---|
| `title` | `"sdci dirs"` |
| `is_satisfied()` | `fs.exists(tasks)` and `fs.exists(uploads)` |
| `apply()` | `fs.make_dir(base, user, "0700")`, then `tasks`, then `uploads` (idempotent) |

Constructed with the operator `user`, an `Fs` adapter, and the derived
`SdciPaths`.

### `Sdci.setup` + `SdciConfigStep` changes

`Sdci.setup` gains two parameters and emits them:
```python
def setup(self, ip, token, uploads_dir, tasks_dir, user) -> None:
    proc = self._run([
        "sdci-server", "setup",
        "--ip", ip, "--token", token,
        "--uploads-dir", uploads_dir, "--tasks-dir", tasks_dir,
        "--user", user,
    ], timeout=SDCI_SETUP_TIMEOUT)
    # raise on non-zero (unchanged)
```

`SdciConfigStep` is constructed with the operator `user` and the `SdciPaths`. Its
`apply()` now:
```python
ip = self._tailscale.ipv4()
if ip is None:
    raise RuntimeError("no Tailscale IPv4 available; is `tailscale up` complete?")
token = self._token_factory()
self._sdci.setup(ip, token, self._paths.uploads, self._paths.tasks, self._user)
self.deployment = SdciDeployment(
    base_dir=self._paths.base,
    tasks_dir=self._paths.tasks,
    uploads_dir=self._paths.uploads,
    token=token,
)
```
`is_satisfied()` unchanged (`/etc/sdci/config` exists → skip; no panel, no regeneration).

### Deploy data model + plumbing

```python
# models_setup.py
class SdciDeployment(BaseModel):
    base_dir: str
    tasks_dir: str
    uploads_dir: str
    token: str

class StepResult(BaseModel):
    title: str
    status: SetupStatus
    detail: str | None = None
    deployment: SdciDeployment | None = None   # replaces `token`
```

`SetupStep` base attribute becomes `deployment: SdciDeployment | None = None`
(was `token`). `run_step` copies `token=step.token` → `deployment=step.deployment`
on the INSTALLED branch.

### Console rendering

`setup_console.render_summary` keeps the counts footer, then — if any step has a
`deployment` — prints a rich `Panel` titled "sdci-server deployed" with rows:
`project` (base_dir), `tasks`, `uploads`, `token`. No panel when absent.

### `build_steps` order

```
User, Docker, Docker group, Tailscale, pipx, sdci, Tailscale up,
SdciDirsStep, SdciConfigStep
```
Both new-area steps are appended only when an auth key is supplied (unchanged
gating). `build_steps` computes `sdci_paths(new_user)` once and passes it to both
the dirs step and the config step; the config step also receives `new_user` for
the `--user` flag.

### `fonfon check`

`SERVICES = ["docker", "ssh", "tailscaled", "sdci-server"]` — the Services
section gains an `sdci-server` row (enabled/active/present via the existing
`SystemdService`). The Packages `sdci` executable item is unchanged.

## Data flow (console, fresh box)

```
run_setup(user, auth_key)
  ... install steps ...
  Tailscale up      -> joins tailnet (100.x)
  sdci dirs         -> install -d .../tasks .../uploads  (operator:operator 0700)
  sdci config       -> ip = tailscale ip -4
                       token = generate_token(42)
                       sdci-server setup --ip --token --uploads-dir --tasks-dir
                       -> StepResult.deployment = SdciDeployment(base,tasks,uploads,token)
  summary           -> rich panel(project/tasks/uploads/token)
```

## Error handling

- Dirs step failure (e.g. missing home) → `FAILED`; run continues. The sdci step
  may then fail when sdci-server rejects the missing dirs — both reported
  `FAILED`, `report.ok` False → exit 1. Consistent with continue-on-error.
- `tailscale up` failure → sdci step finds no IP → `FAILED` (unchanged).
- Idempotent re-run: dirs step `SKIPPED` (dirs exist), sdci step `SKIPPED`
  (`/etc/sdci/config` exists) — no panel, no token regenerated.

## Testing strategy (TDD, injected fakes)

| Layer | How |
|---|---|
| `sdci_paths` | username → base/tasks/uploads strings. |
| `Fs` adapter | fake `run`+`exists`: `make_dir` argv (`install -d -o … -g … -m … path`) + raise on non-zero; `exists` reflects the probe. |
| `SdciDirsStep` | `is_satisfied` follows tasks+uploads existence; `apply` calls `make_dir` for base/tasks/uploads with owner+`0700`. |
| `Sdci.setup` | argv now includes `--uploads-dir`/`--tasks-dir`/`--user`. |
| `SdciConfigStep` | `apply` passes the dirs + operator user to `sdci.setup` and sets `step.deployment` (base/tasks/uploads/token); raises without IP. |
| `run_step` / models | `deployment` propagates on INSTALLED; `SdciDeployment` round-trips in `model_dump`. |
| `build_steps` | with key → order includes `sdci dirs` before `sdci config`; both use the derived paths. |
| Console renderer | panel present (with all four values) on a deployment; absent otherwise. |
| JSON | `deployment` nested object present. |
| `check` | Services section includes an `sdci-server` row (enabled/active/not-found via fake `SystemdService`). |

## Security notes

- Service dirs are `0700` operator-owned — not world-readable.
- sdci-server runs as the unprivileged operator user (`--user`), not root, so a
  compromised service holds only that user's privileges and can reach only its
  own `0700` tree.
- The token continues to be generated with `secrets`, surfaced once, and stored
  by sdci-server in `/etc/sdci/config`; fonfon keeps no copy.

## Open items / future

- Configurable service-tree root, if ever needed (currently derived).
- `check` could later assert the dirs exist / are correctly owned.
