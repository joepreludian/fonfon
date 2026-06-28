# `fonfon check`

`fonfon check` reports whether a server is ready to serve applications. It is
**read-only** — it inspects the system and prints a report; it changes nothing.

## Usage

```bash
fonfon check                # rich, colored table (default)
fonfon check --output json  # machine-readable JSON
```

## What it checks

| Area | Items |
|------|-------|
| System | distro, architecture |
| Packages | `sudo`, `docker-ce`, `tailscale`, `pipx`; plus `sdci` (detected via the `sdci-server` executable on PATH) |
| Services | `docker`, `ssh`, `tailscaled`, `sdci` (systemd enabled/active) |
| Network | per-interface IPv4 + best-effort public IP |
| Docker | whether you have **sudo** (or are root); the docker **socket** is reachable (daemon answers over `/var/run/docker.sock`); the traefik container is **running**; the external `traefik` network created; ports 80/443 published; the dashboard (8080) listening **only** on the tailnet |

## Exit code

`check` exits non-zero if any item fails (a missing package or a disabled
service). Warnings (e.g. traefik not yet configured) and informational items do
not affect the exit code, so `fonfon check` works as a provisioning gate —
**except** two `FAIL` cases that cause a non-zero exit: the docker socket is
unreachable while docker is installed, or Traefik's dashboard is bound to a
public address.

!!! info "sudo, the docker socket, and traefik running"
    The Docker section opens with privilege and reachability facts. **sudo** is
    `OK` when you are root or can elevate via `sudo` (a sudoer who only needs a
    password still counts); otherwise it's `WARN`, since reaching the docker
    socket and running `fonfon setup` need elevation or `docker`-group
    membership.

    **socket** is `OK` when the docker daemon answers over
    `/var/run/docker.sock` — the very socket Traefik mounts to discover
    containers. When it can't be reached, the detail tells you *why* and the
    item is **`FAIL`** (so `check` exits non-zero):

    - **permission denied** — the socket is there but your user can't read it;
      run with sudo or join the `docker` group (see the **sudo** item).
    - **unreachable (is dockerd running?)** — the daemon is down or absent.

    If docker is not installed at all, the docker-specific rows are skipped (the
    **sudo** item is still shown). The **traefik** item is `OK` only when the
    container's state is actually *running* — a container that exists but is
    stopped reports `present but stopped` (`WARN`), no longer a false "running".

!!! warning "Traefik dashboard must stay on the tailnet"
    The Docker section's **dashboard (tailnet-only)** item is `OK` only when
    Traefik's port 8080 is bound to this host's Tailscale IP. If it is bound to a
    public address (`0.0.0.0`), the item is **`FAIL`** and `fonfon check` exits
    non-zero — a publicly reachable dashboard defeats the tailnet-only model. A
    box without Traefik running reports the Docker items as `WARN`, not `FAIL`.

!!! note "Debian-family only"
    Package detection currently supports Debian-family distros (dpkg). On other
    distros the Packages section is skipped.

!!! tip "Scripted use"
    When stdout is not a TTY, rich emits clean JSON without colour codes.
    Pipe directly to `jq` or any other tool:

    ```bash
    fonfon check --output json | jq .
    ```
