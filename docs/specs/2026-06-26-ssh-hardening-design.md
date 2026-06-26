# SSH hardening setup step — design

**Date:** 2026-06-26
**Status:** Approved (pending spec review)
**Topic:** Add SSH-hardening provisioning to `fonfon setup` — install the operator's
`authorized_keys` from a GitHub user and lock `sshd` down to key-only auth.

## Summary

`fonfon setup` gains the ability to harden SSH on the freshly provisioned box:

- **Seed `authorized_keys` from GitHub.** A new flag `--github-user` (env
  `FONFON_GITHUB_USER`) names a GitHub account; fonfon fetches that account's
  public keys from `https://github.com/<user>.keys` and writes them to the
  operator's `~/.ssh/authorized_keys`.
- **Harden `sshd`.** It writes a drop-in
  `/etc/ssh/sshd_config.d/99-fonfon-hardening.conf` that disables root login,
  disables every password path, and enables public-key auth.
- **Never lock you out.** The hardening step **refuses to run** unless the
  operator already has a populated `authorized_keys`, so disabling password auth
  cannot strand you. The keys step likewise refuses to write an empty file when
  the GitHub user has no published keys.
- **Does not restart `sshd`.** Changing live SSH policy mid-session is risky, so
  the step only writes files and then **advises** you to reload SSH (or reboot)
  for the new policy to take effect.

The whole feature is gated on `--github-user`: without it, no SSH step runs and
`fonfon setup` behaves exactly as it does today.

## Decisions

These were settled during brainstorming:

1. **sshd config method:** a **drop-in file**
   `/etc/ssh/sshd_config.d/99-fonfon-hardening.conf`. Debian 12's stock
   `sshd_config` already `Include`s that directory, so the drop-in cleanly
   overrides the distro defaults. Idempotency compares the file's content against
   the rendered content; the distro file is never mangled; reversal is a single
   `rm`.
2. **`authorized_keys` write semantics:** **overwrite** with a fonfon-managed
   file — a `# Managed by fonfon — keys from github.com/<user>.keys` header
   followed by exactly the fetched keys. Predictable and idempotent.
3. **Hardening scope (hardened+):** the three requested directives plus the
   standard companions that actually close the password path:
   - `PermitRootLogin no`
   - `PasswordAuthentication no`
   - `PubkeyAuthentication yes`
   - `KbdInteractiveAuthentication no` (PAM keyboard-interactive can otherwise
     bypass `PasswordAuthentication no`)
   - `PermitEmptyPasswords no`
4. **Key source transport:** stdlib `urllib.request` behind an injectable opener,
   exactly like `system/probes.py::public_ip`. No new runtime dependency, works
   inside the pex.
5. **No service restart:** write-only; advise a reload at the end.
6. **Gating + ordering:** gated on `--github-user`; the two steps run **last**
   in `build_steps` (after Docker has installed `ca-certificates`, which the
   HTTPS fetch to github.com needs, and after any service steps). The hardening
   advisory is therefore the final thing the operator sees.

## CLI surface

```bash
sudo fonfon setup <new_user> \
  --tailscale-key <key> \
  --github-user <github-account>

FONFON_GITHUB_USER=<github-account> \
  sudo -E fonfon setup <new_user> --tailscale-key <key>
```

`--github-user` is optional to `setup` overall (setup without it provisions
everything *except* SSH hardening). When present, the two SSH steps are appended.
`--github-user` composes freely with `--traefik-cert-email`.

## Architecture

The feature follows the established `setup` layering: small, single-purpose
`SetupStep`s (`is_satisfied()` probe + `apply()` mutation), all OS interaction
behind injectable boundary adapters in `system/`, pure rendering in
`services/ssh_config.py`, presentation DTOs in `models_setup.py` rendered by
`output/`.

### Paths

A new helper `services/ssh_paths.py` mirrors `services/sdci_paths.py` /
`services/traefik_paths.py`:

```python
class SshPaths(BaseModel):
    ssh_dir: str          # /home/<user>/.ssh
    authorized_keys: str  # /home/<user>/.ssh/authorized_keys

def ssh_paths(user: str) -> SshPaths: ...
```

### Steps (appended last)

| # | Step (title) | `is_satisfied()` | `apply()` |
|---|--------------|------------------|-----------|
| 13 | **Authorized keys** | `~/.ssh/authorized_keys` exists | fetch `github.com/<github_user>.keys`; raise if none; create `~/.ssh` (`0700`, operator-owned); write `authorized_keys` (`0600`, operator-owned) with the managed header + keys |
| 14 | **SSH hardening** | the drop-in file exists **and** its content equals the rendered hardening config | **lockout guard:** raise if `~/.ssh/authorized_keys` is missing; ensure `/etc/ssh/sshd_config.d` (`0755`, root); write the drop-in (`0644`, root); set `SshDeployment` |

Two steps, mirroring the sdci/Traefik "dirs then config" split: the keys must be
in place before it is safe to disable password auth, and each step is
independently idempotent and reported on its own line. The numbering continues
the existing setup table (12 steps today); these are 13 and 14 because they run
after the optional Traefik steps.

### Generated files

**`~/.ssh/authorized_keys`** (operator-owned, `0600`):

```text
# Managed by fonfon — keys from github.com/<github_user>.keys
ssh-ed25519 AAAAC3Nza...
ssh-rsa AAAAB3Nza...
```

**`/etc/ssh/sshd_config.d/99-fonfon-hardening.conf`** (root-owned, `0644`):

```text
# Managed by fonfon — do not edit. Hardens SSH; see `fonfon setup --github-user`.
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
PermitEmptyPasswords no
```

### Lockout safety ("check the user has keys first")

Two independent guards make it impossible to disable password auth without a
working key path:

1. **Keys step** — `AuthorizedKeysStep.apply()` fetches from GitHub and **raises
   if the result is empty** (a GitHub account with no published keys, or a 404),
   writing nothing. The step is reported `failed`.
2. **Hardening step** — `SshHardeningStep.apply()` checks for the operator's
   `~/.ssh/authorized_keys` and **refuses (raises) if it is absent**. Because the
   local file is the real lockout condition, this holds whether the keys step ran
   this time or was `skipped` because the file already existed.

So if GitHub returns no keys, step 13 fails → `authorized_keys` is absent →
step 14 refuses → `PasswordAuthentication` stays enabled → no lockout. The
continue-on-error policy means the run still completes (exit code `1`) with clear
per-step detail, and the box's existing access is untouched.

## Boundary adapters (new / extended)

- **`GitHubKeys`** — new `system/github_keys.py`. `fetch(username: str) ->
  list[str]` performs `GET https://github.com/<username>.keys` via an injected
  opener (default `urllib.request.urlopen`, matching `probes.public_ip`), returns
  the non-empty stripped lines, and raises `RuntimeError` on any transport/HTTP
  error. An existing user with no keys yields `[]` (the *step* turns that into a
  domain error); a missing user 404s and the adapter raises.
- **`Fs.read_text(path)`** — extend `system/fs.py` with a `read_text` callable
  injected (default `pathlib.Path(p).read_text()`), used by the hardening step's
  content-equality idempotency probe. Sits beside the existing `write_text` /
  `write_file` plumbing.

`~/.ssh` creation and both file writes reuse the existing `Fs.make_dir` /
`Fs.write_file` adapters (owner/mode via `install -d` / `chown` / `chmod`).

## Models and output

- **`models_setup.SshDeployment`** (new pydantic model): `dropin_file`,
  `authorized_keys`, `github_user`, `reload_hint`.
- **`StepResult.deployment`** and **`SetupStep.deployment`** widen from
  `SdciDeployment | TraefikDeployment | None` to
  `SdciDeployment | TraefikDeployment | SshDeployment | None`.
- **`setup_console.render_summary`** — add an `isinstance` branch: for an
  `SshDeployment`, print an `_ssh_panel` (github user, `authorized_keys`,
  drop-in path; `border_style="yellow"` to signal action-needed) **and** a
  prominent advisory line:
  `⚠ Reload SSH to apply: sudo systemctl reload ssh (or reboot the server).`
  The advisory is tied to the deployment, which is only set on `apply()`, so it
  appears exactly when the drop-in was (re)written — not when hardening was
  `skipped` (already in place). Changing `authorized_keys` alone needs no reload
  (sshd reads it per-connection), which is why the advisory hangs off the
  hardening step, not the keys step.
- **JSON output** needs no change — `setup_json.render` dumps the whole report;
  the widened union serialises automatically.

## Wiring

`build_steps(new_user, auth_key=None, cert_email=None, github_user=None,
run=...)` appends the two SSH steps in a top-level `if github_user:` block placed
**after** the `if auth_key:` block:

```python
if github_user:
    spaths = ssh_paths(new_user)
    steps.append(
        AuthorizedKeysStep(
            new_user, github_user, spaths, github=GitHubKeys(), fs=Fs(run=run)
        )
    )
    steps.append(SshHardeningStep(new_user, github_user, spaths, fs=Fs(run=run)))
```

`run_setup` gains a `github_user` parameter threaded to `build_steps`; `cli.py`
passes the value from the new flag (positionally, before the keyword-only
`run`/callbacks). The SSH block is independent of `auth_key` (hardening needs
only the operator user, not the tailnet), so `build_steps("u", None, None,
"octocat")` still appends both SSH steps.

> Note on `ca-certificates`: the HTTPS fetch to github.com requires CA certs,
> which `DockerStep` (step 2) installs via `apt`. Running the SSH steps last
> guarantees they are present by the time the keys step fetches.

## Error handling & idempotency

Unchanged continue-on-error policy:

- **Already satisfied** → `skipped`. The keys step is satisfied once
  `authorized_keys` exists; the hardening step once the drop-in exists with the
  exact rendered content. Re-running a hardened box reports both `skipped`.
- **Applied** → `installed`.
- **Failed** → `failed` with detail; remaining steps continue. Exit code is `1`
  if any step failed.

**Known limitation (matches the Traefik precedent):** because the keys step's
probe is "file exists", a re-run does **not** re-sync `authorized_keys` to
GitHub if the file is already present. To force a re-sync, delete
`~/.ssh/authorized_keys` and re-run. The hardening step, by contrast, *does*
self-heal config drift (it compares content), because security config
correctness matters more than avoiding a rewrite.

## Documentation

- Update `docs/manual/docs/commands/setup.md` — add the `--github-user` usage,
  two rows to the provisioning-steps table, an exit-code/option note, and a new
  **## SSH hardening** section covering the drop-in, the lockout guard, the
  managed `authorized_keys`, and the reload advisory. This is the feature's
  manual entry (SSH hardening is `setup` behaviour, not a standalone service, so
  it lives on the setup page rather than a new nav section).
- No `mkdocs.yml` nav change is required; rebuild the committed `site/`.

## Version

Bump `pyproject.toml` `0.5.1` → `0.6.0` (minor — new feature).

## Out of scope

- Changing the SSH port or `AllowUsers`/`AllowGroups` allow-lists.
- Fetching keys from sources other than GitHub (GitLab, a URL, a local file).
- Re-syncing `authorized_keys` on re-run (see Known limitation).
- A `fonfon check` probe for SSH posture (could read the drop-in / `sshd -T`
  later).
- Reloading or restarting `sshd` automatically.

## Testing (TDD)

- `tests/test_ssh_paths.py` — path derivation.
- `tests/test_fs.py` — `read_text` returns file contents via the injected reader.
- `tests/test_github_keys.py` — `fetch` builds the `<user>.keys` URL, returns key
  lines, returns `[]` on empty body, raises on transport error.
- `tests/test_ssh_config.py` — the drop-in carries all five directives + a
  managed header; `authorized_keys` rendering has the header and keys.
- `tests/test_setup_steps.py` — `AuthorizedKeysStep` (satisfied/unsatisfied;
  apply fetches, creates `~/.ssh` `0700`, writes `authorized_keys` `0600` with
  the keys; raises and writes nothing on no keys) and `SshHardeningStep`
  (satisfied only when content matches; apply refuses without `authorized_keys`;
  apply ensures the drop-in dir, writes the drop-in `0644` root, sets
  `SshDeployment`).
- `tests/test_setup.py` — `build_steps` appends the SSH steps last only when
  `github_user` is supplied, with or without an auth key.
- `tests/test_cli_setup.py` — `--github-user` / `FONFON_GITHUB_USER` plumbing
  reaches `run_setup`.
- `tests/test_setup_output.py` — the SSH panel renders and the reload advisory is
  printed; coexists with the sdci/Traefik panels.
- `tests/test_models_setup.py` — `SshDeployment` and the widened union.
