# `fonfon setup`

`fonfon setup` provisions a server from scratch. It creates an operator user,
installs Docker (via the official apt repository), adds the user to the Docker
group, installs Tailscale (via the official install script), installs pipx, and
installs sdci globally via pipx. Each step is **idempotent**: if the system
already satisfies a step, it is skipped — so `setup` is safe to re-run.

!!! warning "Must run as root"
    `fonfon setup` requires `root` (or `sudo`). It will refuse and exit non-zero
    if run as an unprivileged user.

## Usage

```bash
sudo fonfon setup <new_user>                  # rich, colored table (default)
sudo fonfon setup <new_user> --output json    # machine-readable JSON
```

`<new_user>` is the name of the operator account to create (e.g. `deploy`).

## Provisioning steps

| # | Step | What it does |
|---|------|--------------|
| 1 | **User** | Creates `<new_user>` with a home directory and adds it to the `sudo` group |
| 2 | **Docker** | Adds the official Docker apt keyring and repository, then installs `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`, and `docker-compose-plugin` |
| 3 | **Docker group** | Adds `<new_user>` to the `docker` group so containers can be managed without `sudo` |
| 4 | **Tailscale** | Runs the official `curl \| sh` install script from `tailscale.com` |
| 5 | **pipx** | Installs `pipx` via apt |
| 6 | **sdci** | Installs `sdci` globally via pipx (`PIPX_HOME=/opt/pipx`, `PIPX_BIN_DIR=/usr/local/bin`) so it is available system-wide |

## Idempotency and error handling

Each step probes the system before acting:

- **Already satisfied** → status `skipped` (no changes made).
- **Applied successfully** → status `installed`.
- **Failed** → status `failed` (detail included); remaining steps **continue**
  (continue-on-error). The final exit code is **1** if any step failed, **0**
  if all steps installed or skipped.

Running `fonfon setup` twice on a fully provisioned server will report every
step as `skipped` and exit `0`.

## Exit code

| Condition | Exit code |
|-----------|-----------|
| All steps installed or skipped | `0` |
| One or more steps failed | `1` |
| Not run as root | `1` |

## JSON output

```bash
sudo fonfon setup deploy --output json | jq .
```

The JSON payload contains a `steps` array, each entry with `title`, `status`
(`installed` \| `skipped` \| `failed`), and an optional `detail` string.

## sdci and `fonfon check`

After `setup` completes, `fonfon check` validates sdci presence via the global
pipx environment (`PIPX_HOME=/opt/pipx`). If sdci is not found there, the
Packages section of the check report marks it as `FAIL`.

!!! note "Debian-family only"
    Docker installation uses `apt`/`dpkg` and targets Debian. Tailscale and
    pipx steps are distro-agnostic.
