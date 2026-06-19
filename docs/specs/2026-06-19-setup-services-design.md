# `fonfon setup` service configuration (Tailscale up + sdci-server) — Design

- **Date:** 2026-06-19
- **Status:** Approved (design); not yet implemented
- **Topic:** Extend `fonfon setup <new_user>` to *configure* the installed
  services — join the Tailscale tailnet and configure `sdci-server` against the
  resulting tailnet IP — on top of the existing *install* steps.

## Context & motivation

`fonfon setup` today installs the base stack (Docker, Tailscale, pipx, sdci) and
prepares an operator user, but stops short of making the services usable: it
never joins a tailnet and never points `sdci-server` at one. This was an
explicit "later" item in the setup design.

This change closes that gap. With a Tailscale auth key, `fonfon setup` now also:

1. **Joins the tailnet** — `tailscale up --auth-key <key>`, yielding a `100.x`
   tailnet IPv4.
2. **Configures sdci-server** — generates a random 42-char token and runs
   `sdci-server setup --ip <tailnet-ip> --token <token>`. `sdci-server` persists
   its config to `/etc/sdci/config` and self-registers its own systemd unit.

It keeps the existing model: each action is an idempotent `SetupStep`
(check-then-act), the command continues past failed steps, and results are
reported per-step.

## Goals

- Add two configuration steps to `fonfon setup`, after the install steps:
  **Tailscale up** then **sdci config**.
- Add a **required** `--tailscale-auth-key` option (with a
  `FONFON_TAILSCALE_AUTH_KEY` env fallback).
- Generate the sdci token in fonfon, pass it to `sdci-server setup`, and surface
  the value to the operator (console + json).
- Keep everything idempotent and continue-on-error, reusing the `SetupStep`
  abstraction and the injectable-runner adapter pattern.

## Non-goals

- Writing or owning a systemd unit for `sdci-server` — `sdci-server setup`
  self-registers and enables its own unit.
- Persisting the token to a fonfon-owned file — `sdci-server` stores it in
  `/etc/sdci/config`; fonfon only generates and prints it.
- Changes to `fonfon check` — it already reports `tailscaled` enabled and
  `sdci-server` present; "configured" status is out of scope (YAGNI).
- Non-Debian support; SSH hardening; `--dry-run` (consistent with the setup design).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the config lives | **Appended to `fonfon setup`**, not a separate command | Matches "fonfon setup needs the param"; one command provisions a box end-to-end. |
| `--tailscale-auth-key` | **Required**; abort early (before any step) if absent | Configuration is the point of this change; a clear pre-flight gate beats a half-provisioned box. |
| Missing-key behavior | Print message + link to the Tailscale keys page, `exit 1`, take **no** action | Mirrors the root gate: fail fast, change nothing. |
| Auth-key source | CLI option **or** `FONFON_TAILSCALE_AUTH_KEY` env | Env keeps the secret out of shell history / `ps`; also convenient for `make debian-demo`. |
| sdci systemd | **`sdci-server setup` self-registers** its unit | No unit template in fonfon; fonfon can verify `systemctl is-active sdci-server` afterward. |
| Step structure | **Two independent, stateless steps** | Per-action ✓/✗ reporting; no shared-context plumbing through `run_setup`. |
| IP hand-off | **sdci step re-derives the IP** via `tailscale ip -4` | Keeps steps stateless; if Tailscale isn't up the sdci step fails cleanly. |
| Token | **Generated in fonfon** (42 chars, `[A-Za-z0-9]`), printed; persisted by sdci | Operator needs it to configure clients; `secrets`-based, surfaced once. |
| IP family / flags | **IPv4** (`tailscale ip -4`); `tailscale up` with only `--auth-key` | Simplest correct default for sdci; extra flags are YAGNI. |

## Architecture

The change is additive — it reuses the `SetupStep`, `run_step`, `run_setup`,
`SetupReport` machinery unchanged in shape, adding two steps, two boundary
adapters, a token helper, a CLI option/gate, and a `token` field for surfacing.

### New steps (ordered after the existing six)

| # | Step | `is_satisfied()` (skip when) | `apply()` |
|---|------|------------------------------|-----------|
| 7 | **Tailscale up** | `Tailscale.ipv4()` returns an IPv4 (already on the tailnet) | `Tailscale.up(auth_key)` → `tailscale up --auth-key <key>` (≈60s timeout); raise on failure |
| 8 | **sdci config** | `Sdci.is_configured()` → `/etc/sdci/config` exists | `ip = Tailscale.ipv4()` (raise if `None`); `token = generate_token()`; `Sdci.setup(ip, token)` → `sdci-server setup --ip <ip> --token <token>`; raise on failure. Surfaces the generated token. |

No shared state: the sdci step re-derives the IP itself. If step 7 failed (no
tailnet), step 8's `apply()` raises (`ip is None`) and is reported `FAILED`,
while `run_setup` continues and the summary shows both ✗.

### CLI

`fonfon setup <new_user> --tailscale-auth-key <key> [-o/--output console|json]`:

1. **Root gate** (existing) — `os.geteuid() != 0` → error, `exit 1`.
2. **Auth-key gate** (new) — resolve from `--tailscale-auth-key` or
   `FONFON_TAILSCALE_AUTH_KEY`; if empty, print a message + the keys-page link
   and `exit 1`, taking no action:

   ```
   fonfon setup requires a Tailscale auth key.
   Generate one at: https://login.tailscale.com/admin/settings/keys
   Then re-run: fonfon setup <user> --tailscale-auth-key <key>
   ```

3. `report = run_setup(new_user, auth_key, ...)`, render, `exit 0 if report.ok else 1`.

`run_setup(new_user, auth_key, ...)` threads `auth_key` into `build_steps`, which
constructs the Tailscale-up step with it.

### New boundary adapters (`system/`, injectable `run` seam)

- **`Tailscale`** (`system/tailscale.py`)
  - `up(auth_key: str) -> None` — `tailscale up --auth-key <key>` (timeout ≈60s);
    raise `RuntimeError` on non-zero, including stderr/stdout.
  - `ipv4() -> str | None` — `tailscale ip -4`; return the first non-empty line,
    or `None` if the command fails or prints nothing.
- **`Sdci`** (`system/sdci.py`)
  - `setup(ip: str, token: str) -> None` — `sdci-server setup --ip <ip> --token
    <token>`; raise `RuntimeError` on non-zero.
  - `is_configured() -> bool` — `/etc/sdci/config` exists (via an injectable
    `exists` callable defaulting to `os.path.exists`, keeping it unit-testable).

Both run through `system/_run.py` (which already swallows
`FileNotFoundError`/`TimeoutExpired`), so they are unit-testable with fakes.

### Token generation

`generate_token(length: int = 42) -> str` — `secrets.choice` over
`string.ascii_letters + string.digits`. A small standalone helper (e.g.
`services/token.py`); no I/O, trivially tested for length and alphabet.

### Token surfacing

The sdci step is the only step that produces a value the caller needs. To carry
it back without breaking the uniform `run_step` policy:

- `StepResult` gains an optional `token: str | None = None`.
- The sdci step exposes the token it generated (e.g. via the step instance after
  `apply()`); `run_step` copies it onto the `StepResult` for that step. Steps
  that generate no token leave it `None`.
- **console**: the summary prints the token prominently when present, e.g.
  `sdci token: <token>  (stored in /etc/sdci/config)`.
- **json**: the token appears as the `token` field on that step's result.
- On an **idempotent skip** (`/etc/sdci/config` already exists), no token is
  generated; the step reports `SKIPPED` ("already configured") and `token` stays
  `None`.

## Data flow

```
CLI: resolve auth_key (option | env)  --(missing)-->  print link, exit 1
  |
  v
run_setup(new_user, auth_key)
  |
  +-- ...existing 6 install steps...
  +-- TailscaleUp.apply():  tailscale up --auth-key <key>     -> joins tailnet
  +-- SdciConfig.apply():   ip = tailscale ip -4
  |                         token = generate_token(42)
  |                         sdci-server setup --ip <ip> --token <token>
  |                           -> sdci writes /etc/sdci/config, enables its unit
  v
SetupReport (StepResult.token set on the sdci step)
  -> console summary prints token | json includes token
```

## Error handling

- **Missing key** → pre-flight `exit 1`, nothing mutated.
- **`tailscale up` fails** → Tailscale-up step `FAILED`; sdci step then finds no
  IP and is `FAILED`; `run_setup` continues; `report.ok` is False → `exit 1`.
- **`sdci-server setup` fails** → sdci step `FAILED` with the captured stderr.
- All consistent with the existing continue-on-error policy; `report.ok` gates
  the exit code.

## Tooling: `make debian-demo`

`tools/debian-dev.sh demo` runs `fonfon setup preludian` with no key, which now
hits the required-key abort. Update the `demo` flow to pass
`--tailscale-auth-key "$TAILSCALE_AUTH_KEY"` sourced from the environment. When
the env var is unset, the run still executes and demonstrates the abort message
(documented in the script's help), so the demo stays runnable without a real key.

## Testing strategy (TDD, injected runners)

| Layer | How |
|---|---|
| `Tailscale` adapter | Fake `run`: `up` asserts argv + raises on non-zero; `ipv4` parses a line, returns `None` on failure/empty. |
| `Sdci` adapter | Fake `run` + fake `exists`: `setup` asserts argv + raises on non-zero; `is_configured` reflects the `exists` probe. |
| `generate_token` | Length == 42; every char in `[A-Za-z0-9]`; two calls differ. |
| **TailscaleUp** step | Satisfied when `ipv4()` returns an IP → `is_satisfied` True; unsatisfied + `apply` ok; `apply` raises on failure. |
| **SdciConfig** step | `is_satisfied` follows `/etc/sdci/config`; `apply` happy path issues `sdci-server setup` with the derived IP + generated token and exposes the token; `apply` raises when `ipv4()` is `None`. |
| `run_step` token plumbing | The sdci step's generated token lands on its `StepResult.token`; other steps leave it `None`. |
| `run_setup` | Threads `auth_key` into `build_steps`; full ordered run including the two new steps. |
| CLI key-gate | `CliRunner`: missing key (no option, no env) → link printed, `exit 1`, `run_setup` not called; env fallback resolves; option present runs. |
| Renderers | console prints the token when present and omits it on skip; json includes the `token` field. |
| Integration (Lima) | `sudo fonfon setup <u> --tailscale-auth-key <key>` on real Debian (key via env); a second run reports the two new steps `SKIPPED`. |

## Security notes

- The auth key is a secret: the `FONFON_TAILSCALE_AUTH_KEY` env fallback lets the
  operator avoid putting it in shell history or an argv visible in `ps`.
- The sdci token is generated with `secrets` (CSPRNG), printed once for the
  operator, and stored by `sdci-server` in `/etc/sdci/config`. Fonfon does not
  write its own copy.
- Both steps run only after the existing root gate.

## Open items / future

- `fonfon check` could later report tailnet membership and sdci-configured state.
- `tailscale up` flags (`--ssh`, `--accept-routes`, `--hostname`) if a use case
  appears; out of scope now.
- Re-keying / token rotation (today a configured box is skipped, never rotated).
