# Debian Integration Test Harness — Design

- **Date:** 2026-06-18
- **Status:** Approved (design); not yet implemented
- **Topic:** An automated harness to validate the `fonfon` executable against a real Debian system.

## Context & motivation

Fonfon is an opinionated VPS configurator: it hardens SSH, installs packages
(Docker, Tailscale, SDCI), and sets up systemd services on a fresh Linux
server. Those behaviors can only be trusted if they are exercised against a
faithful target — a real kernel, real systemd as PID 1, real Docker and
Tailscale, and the ability to reboot and confirm services persist.

A systemd-enabled Docker container was considered and rejected as the primary
target: Fonfon installs Docker (container-in-container / DinD is unrepresentative),
installs Tailscale (needs `/dev/net/tun` + real netfilter), and benefits from
reboot testing (containers can't reboot). On macOS the problem compounds —
Docker is already a LinuxKit VM. A real VM avoids all of this.

Note: Fonfon's provisioning features are **not implemented yet** (today it is
just the CLI banner). The deliverable here is the **harness**; assertions grow
as each feature lands.

## Goals

- Boot a fresh Debian VM, run the built `fonfon` scie inside it, and assert
  behavior — reproducibly, with one command.
- Start with a smoke assertion and provide a clear place for richer
  service/systemd assertions to accrete.
- Keep the fast inner loop fast on Apple Silicon; allow full-coverage runs.

## Non-goals

- CI wiring (left unblocked but out of scope — GitHub's Linux runners expose
  `/dev/kvm`, and Lima runs on Linux).
- A systemd-in-Docker "fast smoke" layer (may be added later for the
  container-safe subset; not part of this design).
- Actually joining a Tailscale tailnet (needs a secret auth key; deferred).

## Success criteria (today)

- `make test-integration` boots a Debian **aarch64** VM, runs the aarch64
  `fonfon` scie inside it, and an integration test asserts `fonfon --version`
  exits 0 and reports `0.1.0`.
- `make test-integration ARCH=x86_64` performs the same against an emulated
  **x86_64** Debian VM.
- Teardown leaves no VM behind, even on failure.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| VM tooling | **Lima** (`limactl`) | Ergonomic on macOS (HVF-accelerated aarch64), Debian cloud image + cloud-init, automatic SSH port-forward and project mount, scriptable YAML; also runs on Linux, so not a CI dead-end. |
| Architecture | **aarch64 default, x86_64 opt-in** | aarch64 is HVF-accelerated (fast loop); x86_64 is emulated (slower) and reserved for occasional full-coverage / CI parity, selected via `ARCH=x86_64`. |
| Responsibility split | **Lifecycle in shell, assertions in pytest** | `run.sh` owns boot/inject/teardown; `pytest` asserts against the running VM over Lima's SSH. Keeps pytest simple and reuses the existing test stack. |
| Reset strategy | **Fresh VM per run** | Reproducible. The Debian base image is cached by Lima, so only cloud-init re-runs. |
| Distro | **Debian 12 (bookworm)** | Stable cloud image and tooling; pinned in the Lima template and trivially swappable to 13 (trixie). |

## Components & layout

```
tests/integration/
  lima-debian.yaml   # Lima template: Debian 12 cloud image, arch parametrized
  run.sh             # lifecycle: build scie for ARCH -> start VM -> inject scie
                     #            -> run fonfon -> run pytest -> teardown (trap-cleaned)
  conftest.py        # pytest fixture exposing ssh_run(cmd) bound to the running VM;
                     # skips the integration suite if no VM/SSH config is present
  test_smoke.py      # @pytest.mark.integration assertions (version/banner now)
Makefile             # + `test` (unit, fast) and `test-integration` (ARCH ?= aarch64)
pyproject.toml       # register the `integration` marker; default `uv run pytest`
                     # stays unit-only (`-m "not integration"`)
```

Each unit has one job:
- **`lima-debian.yaml`** — declares the guest (image, arch, mounts, cloud-init).
- **`run.sh`** — orchestrates the run; the only thing that manages VM lifecycle.
- **`conftest.py`** — turns "a running VM" into an `ssh_run` helper for tests.
- **`test_smoke.py`** — the assertions; the file that grows per Fonfon feature.

## Flow: `make test-integration`

1. Build the scie for `ARCH` (reuse the `pex --scie` step from the build).
2. `limactl start` a fresh VM from `lima-debian.yaml` (image cached; aarch64 via
   HVF, or emulated x86_64 when `ARCH=x86_64`).
3. Inject the scie into the VM (via Lima's auto-mounted project dir).
4. Run `fonfon` in the VM via `sudo` (provisioning needs root).
5. `uv run pytest -m integration` connects over Lima's SSH config and asserts.
6. Teardown (`limactl stop && limactl delete`) via a `trap`, even on failure.

## Prerequisites

- **Lima** is a host tool (`brew install lima`), not a uv dependency. `run.sh`
  checks for it and prints install guidance if missing.
- No new Python dependencies: tests run VM commands via `subprocess` using the
  SSH config Lima emits.

## Roadmap: future assertions (designed-for, not built now)

As Fonfon's features land, add assertions to `test_smoke.py` (or sibling files):

- `systemctl is-active docker tailscaled ssh` after provisioning.
- `sshd -T` reflects the hardened configuration.
- `docker run --rm hello-world` succeeds.
- **Reboot**, then re-assert that enabled services come back up.
- Tailscale: assert install/enable now; join a tailnet later using an
  ephemeral auth key supplied as a secret.

## Risks & open items

- **x86_64 emulation is slow** on Apple Silicon — acceptable because it is
  opt-in, not the default loop.
- **Running `fonfon` needs root** in the guest; the harness invokes it via
  `sudo`.
- **Debian version**: defaulted to 12 (bookworm); revisit if a feature needs
  13 (trixie).
- **Tailscale auth** requires a secret before tailnet-join can be asserted;
  tracked as future work above.
