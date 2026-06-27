# `fonfon setup`

`fonfon setup` provisions a server from scratch. It creates an operator user,
installs Docker (via the official apt repository), adds the user to the Docker
group, installs Tailscale (via the official install script), installs pipx, and
installs sdci globally via pipx. With a Tailscale auth key it then **joins the
tailnet** and **configures `sdci-server`** against the tailnet IP. Each step is
**idempotent**: if the system already satisfies a step, it is skipped — so
`setup` is safe to re-run.

!!! warning "Must run as root"
    `fonfon setup` requires `root` (or `sudo`). It will refuse and exit non-zero
    if run as an unprivileged user.

!!! warning "Requires a Tailscale auth key"
    `fonfon setup` requires `--tailscale-key` (or the
    `FONFON_TAILSCALE_KEY` environment variable). Without it, setup prints a
    link to the [Tailscale keys page](https://login.tailscale.com/admin/settings/keys)
    and exits non-zero **without making any changes**. Using the environment
    variable keeps the key out of your shell history.

## Usage

```bash
sudo fonfon setup <new_user> --tailscale-key <key>   # rich, colored (default)
sudo fonfon setup <new_user> --tailscale-key <key> --output json
FONFON_TAILSCALE_KEY=<key> sudo -E fonfon setup <new_user>   # key via env
```

`<new_user>` is the name of the operator account to create (e.g. `deploy`).

To also deploy Traefik (reverse proxy with tailnet-only dashboard and Let's
Encrypt certificates), pass `--traefik-cert-email` (or set
`FONFON_TRAEFIK_CERT_EMAIL`):

```bash
sudo fonfon setup deploy --tailscale-key <key> \
  --traefik-cert-email you@example.com
```

See [Services → Traefik](../services/traefik.md) for the full model and the
application label cookbook.

To also harden SSH — install the operator's `authorized_keys` from a GitHub
account and lock `sshd` down to key-only auth — pass `--github-user` (or set
`FONFON_GITHUB_USER`):

```bash
sudo fonfon setup deploy --tailscale-key <key> --github-user your-gh-handle
```

## Provisioning steps

| # | Step | What it does |
|---|------|--------------|
| 1 | **User** | Creates `<new_user>` with a home directory and adds it to the `sudo` group |
| 2 | **Docker** | Adds the official Docker apt keyring and repository, then installs `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`, and `docker-compose-plugin` |
| 3 | **Docker group** | Adds `<new_user>` to the `docker` group so containers can be managed without `sudo` |
| 4 | **Tailscale** | Runs the official `curl \| sh` install script from `tailscale.com` |
| 5 | **pipx** | Installs `pipx` via apt |
| 6 | **sdci** | Installs the `sdci` pipx package globally (`PIPX_HOME=/opt/pipx`, `PIPX_BIN_DIR=/usr/local/bin`), which provides the `sdci-server` executable |
| 7 | **Tailscale up** | Joins the tailnet with `tailscale up --auth-key <key>`, yielding a `100.x` tailnet IPv4 (skipped if already connected) |
| 8 | **sdci dirs** | Creates `/home/<user>/services/sdci/{tasks,uploads}`, owned by the operator user, mode `0700` (skipped if they already exist) |
| 9 | **sdci config** | Generates a random 42-char token and runs `sdci-server setup --ip <tailnet-ip> --token <token> --uploads-dir <…/uploads> --tasks-dir <…/tasks> --user <user>`, so the service runs as the operator user; stores config in `/etc/sdci/config` and registers its own systemd unit (skipped if `/etc/sdci/config` exists) |
| 10 | **Traefik dirs** | Creates `/home/<user>/services/traefik/{,acme,dynamic}`, owned by the operator, mode `0700` (only when `--traefik-cert-email` is set) |
| 11 | **Traefik network** | Creates the external `traefik` Docker network so app stacks can attach |
| 12 | **Traefik** | Writes `docker-compose.yml` (image `traefik:v3.7.5`) + `traefik.yml`, then `docker compose up -d`; dashboard bound to `<tailnet-ip>:8080`, ACME HTTP-01 resolver `le` |
| 13 | **Authorized keys** | Fetches `https://github.com/<github-user>.keys` and writes `~/.ssh/authorized_keys` (mode `0600`, operator-owned) under a managed header (only when `--github-user` is set). **Fails, writing nothing, if that GitHub account has no public keys.** |
| 14 | **SSH hardening** | Writes `/etc/ssh/sshd_config.d/99-fonfon-hardening.conf` (`PermitRootLogin no`, `PasswordAuthentication no`, `PubkeyAuthentication yes`, `KbdInteractiveAuthentication no`, `PermitEmptyPasswords no`). **Refuses if the operator has no `authorized_keys`** (lockout guard). Does **not** restart `sshd` — advises a reload. |

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
| No Tailscale auth key provided | `1` |

## JSON output

```bash
sudo fonfon setup deploy --output json | jq .
```

The JSON payload contains a `steps` array, each entry with `title`, `status`
(`installed` \| `skipped` \| `failed`), an optional `detail` string, and an
optional `deployment` object on the relevant step — sdci (`base_dir`,
`tasks_dir`, `uploads_dir`, `token`), Traefik, or SSH (`dropin_file`,
`authorized_keys`, `github_user`, `reload_hint`).

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

## sdci and `fonfon check`

After `setup` completes, `fonfon check` validates sdci presence by checking
whether the `sdci-server` executable is on PATH. The `sdci` pipx package places
this executable in `/usr/local/bin` (`PIPX_BIN_DIR`). If `sdci-server` is not
found, the Packages section of the check report marks it as `FAIL`. In addition,
`fonfon check` reports the `sdci` systemd unit in the **Services** section
— it must be enabled and active for that check to pass.

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

!!! note "Debian-family only"
    Docker installation uses `apt`/`dpkg` and targets Debian. Tailscale and
    pipx steps are distro-agnostic.
