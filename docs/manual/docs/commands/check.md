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
| Docker | traefik running, listening on 80/443, attached to an external network |

## Exit code

`check` exits non-zero if any item fails (a missing package or a disabled
service). Warnings (e.g. traefik not yet configured) and informational items do
not affect the exit code, so `fonfon check` works as a provisioning gate.

!!! note "Debian-family only"
    Package detection currently supports Debian-family distros (dpkg). On other
    distros the Packages section is skipped.

!!! tip "Scripted use"
    When stdout is not a TTY, rich emits clean JSON without colour codes.
    Pipe directly to `jq` or any other tool:

    ```bash
    fonfon check --output json | jq .
    ```
