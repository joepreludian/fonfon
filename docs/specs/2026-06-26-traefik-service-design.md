# Traefik service setup step — design

**Date:** 2026-06-26
**Status:** Approved (pending spec review)
**Topic:** Add a Traefik reverse-proxy provisioning step to `fonfon setup`.

## Summary

`fonfon setup` gains the ability to provision [Traefik](https://traefik.io) as a
Docker-Compose service that acts as the server's edge reverse proxy. Traefik:

- Serves applications publicly on **:80** (HTTP→HTTPS redirect and the ACME
  HTTP-01 challenge) and **:443** (TLS).
- Exposes its **dashboard/API only on the tailnet** — bound to the host's
  Tailscale IPv4 on port 8080, unreachable from the public internet.
- Creates an **external Docker network** named `traefik` so other Compose stacks
  can attach to it.
- **Does not auto-expose containers**: `providers.docker.exposedByDefault` is
  `false`. Each application opts in with `traefik.*` labels and obtains HTTPS via
  `tls.certresolver=le`.

The feature is gated on a new flag `--traefik-cert-email` (env
`FONFON_TRAEFIK_CERT_EMAIL`). Traefik also needs the host's tailnet IP for the
dashboard binding, so its steps run inside the existing `if auth_key:` branch of
`build_steps`, additionally gated on the cert email being present. Without
`--traefik-cert-email`, no Traefik step runs and `fonfon setup` behaves exactly
as it does today.

## Decisions

These were settled during brainstorming:

1. **Certificate strategy:** Let's Encrypt **HTTP-01** challenge on the `web`
   entrypoint (port 80). No DNS-provider credentials required.
2. **Cert email:** a **required** CLI flag `--traefik-cert-email` (env
   `FONFON_TRAEFIK_CERT_EMAIL`). Traefik is provisioned only when it is supplied.
3. **Lifecycle:** the step **writes files and starts the stack** —
   `docker compose up -d` — so Traefik is live after `setup`. Idempotency probes
   that the container is running.
4. **Image pin:** `traefik:v3.7.5`.
5. **Network name:** `traefik`.
6. **Dashboard security:** `api.insecure: true` exposes the dashboard on the
   container's `:8080`, made tailnet-only by publishing it on the host as
   `<tailnet_ip>:8080:8080` (it binds solely to the Tailscale interface).

## CLI surface

```bash
sudo fonfon setup <new_user> \
  --tailscale-key <key> \
  --traefik-cert-email you@example.com

FONFON_TRAEFIK_CERT_EMAIL=you@example.com \
  sudo -E fonfon setup <new_user> --tailscale-key <key>
```

`--traefik-cert-email` is optional to `setup` overall (setup without it provisions
everything *except* Traefik). When present, the three Traefik steps are appended.

> The working-tree `cli.py` has a name mismatch: the option is `--tailscale-key`
> (dest `tailscale_key`) while the `setup()` parameter is `tailscale_auth_key`, so
> the binding is currently broken. Since the `setup()` signature is edited here to
> add the cert-email parameter, the parameter is renamed `tailscale_auth_key` →
> `tailscale_key` to match the option. The stale `--tailscale-auth-key` /
> `FONFON_TAILSCALE_AUTH_KEY` references in `commands/setup.md` are corrected to
> `--tailscale-key` / `FONFON_TAILSCALE_KEY` while that doc is being edited.

## Architecture

The feature follows the established `setup` layering: small, single-purpose
`SetupStep`s (`is_satisfied()` probe + `apply()` mutation), all OS interaction
behind injectable boundary adapters in `system/`, and presentation DTOs in
`models_setup.py` rendered by `output/`.

### Paths

A new helper `services/traefik_paths.py` mirrors `services/sdci_paths.py`:

```python
class TraefikPaths(BaseModel):
    base: str           # /home/<user>/services/traefik
    acme: str           # <base>/acme
    dynamic: str        # <base>/dynamic
    compose_file: str   # <base>/docker-compose.yml
    static_config: str  # <base>/traefik.yml

def traefik_paths(user: str) -> TraefikPaths: ...
```

### Steps (appended after `sdci config`)

| # | Step (title) | `is_satisfied()` | `apply()` |
|---|--------------|------------------|-----------|
| 10 | **Traefik dirs** | `base`, `acme`, `dynamic` all exist | create `~/services/traefik/{,acme,dynamic}`, owned by the operator user, mode `0700` |
| 11 | **Traefik network** | `docker network inspect traefik` succeeds | `docker network create traefik` |
| 12 | **Traefik** | `traefik` container exists and `State.Running` is true | write `docker-compose.yml` + `traefik.yml`, run `docker compose up -d`, set `TraefikDeployment` |

This split mirrors the sdci precedent (`SdciDirsStep` separate from
`SdciConfigStep`). Each step is independently idempotent and reported on its own
line. Order rationale: directories must exist before files are written into them;
the external network must exist before the container that attaches to it starts.

### Generated files

**`~/services/traefik/traefik.yml`** (static configuration):

```yaml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

api:
  dashboard: true
  insecure: true            # dashboard on :8080; tailnet-only via the port binding

providers:
  docker:
    exposedByDefault: false # apps must opt in with labels
    network: traefik
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  le:
    acme:
      email: <cert_email>
      storage: /acme/acme.json
      httpChallenge:
        entryPoint: web
```

**`~/services/traefik/docker-compose.yml`**:

```yaml
services:
  traefik:
    image: traefik:v3.7.5
    container_name: traefik
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "<tailnet_ip>:8080:8080"   # dashboard bound to the Tailscale IP only
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik.yml:/etc/traefik/traefik.yml:ro
      - ./dynamic:/etc/traefik/dynamic:ro
      - ./acme:/acme
    networks:
      - traefik

networks:
  traefik:
    external: true
```

The `<tailnet_ip>` is resolved at write time via `Tailscale.ipv4()` (the same
source `SdciConfigStep` uses). Publishing `8080` against that address binds the
dashboard solely to the Tailscale interface; 80/443 publish on all interfaces and
remain public. The ACME HTTP-01 challenge still works despite the global `web`
redirect — Traefik serves the `/.well-known/acme-challenge/` path ahead of the
redirect router.

### Dashboard-on-tailnet mechanism

`api.insecure: true` serves the dashboard on the `traefik` entrypoint (`:8080`)
with no authentication. Network-level isolation — not Traefik auth — provides
access control: the host only publishes `8080` on `<tailnet_ip>`, so the
dashboard is reachable exclusively over the tailnet. This matches the request
that "its management service listen ONLY on tailscale".

## Boundary adapters (new / extended)

- **`Fs.write_file(path, content, owner, mode)`** — extend `system/fs.py`. A
  `write_text` callable is injected (default `pathlib.Path(p).write_text(c)`) for
  testability; ownership and mode are applied via the injected runner
  (`chown owner:owner`, `chmod mode`), the same pattern `make_dir` already uses.
- **`DockerCli.network_exists(name)` / `DockerCli.create_network(name)`** —
  extend `system/docker_cli.py`. `network_exists` runs `docker network inspect`
  and returns `proc.returncode == 0`; `create_network` runs
  `docker network create <name>` and raises on non-zero.
- **`DockerCompose.up(compose_file)`** — new `system/docker_compose.py`, runs
  `docker compose -f <compose_file> up -d` and raises on failure. The
  "is it running" probe reuses `DockerCli.inspect_container("traefik")` and reads
  `State.Running`, so no new probe adapter is needed.

## Models and output

- **`models_setup.TraefikDeployment`** (new pydantic model):
  `compose_file`, `network`, `dashboard_url`
  (`http://<tailnet_ip>:8080/dashboard/`), `cert_email`.
- **`StepResult.deployment`** and **`SetupStep.deployment`** widen from
  `SdciDeployment | None` to `SdciDeployment | TraefikDeployment | None`.
- **`setup_console.render_summary`** — render *all* deployments rather than the
  first: iterate `report.steps`, and for each step that carries a deployment
  dispatch to the matching panel (`_deployment_panel` for sdci,
  `_traefik_panel` for Traefik) by `isinstance`. The Traefik panel shows the
  compose file, network name, dashboard URL, and cert email.
- **JSON output** needs no change — `setup_json.render` dumps the whole report;
  the widened union serialises automatically.

## Wiring

`build_steps(new_user, auth_key=None, cert_email=None, run=...)` appends the
three Traefik steps inside the existing `if auth_key:` block, only when
`cert_email` is truthy:

```python
if auth_key:
    ...
    if cert_email:
        tpaths = traefik_paths(new_user)
        steps.append(TraefikDirsStep(new_user, tpaths, fs=Fs(run=run)))
        steps.append(TraefikNetworkStep(docker=DockerCli(run=run)))
        steps.append(
            TraefikStep(
                new_user, tpaths, cert_email,
                tailscale=Tailscale(run=run),
                docker=DockerCli(run=run),
                compose=DockerCompose(run=run),
                fs=Fs(run=run),
            )
        )
```

`run_setup` gains a `cert_email` parameter threaded to `build_steps`; `cli.py`
passes the value from the new flag.

## Error handling & idempotency

Unchanged policy (continue-on-error):

- **Already satisfied** → `skipped`. Re-running on a server where Traefik is up
  reports all three steps as `skipped` and changes nothing.
- **Applied** → `installed`.
- **Failed** → `failed` with detail; remaining steps continue. Exit code is `1`
  if any step failed.

**Known limitation:** step 12's `is_satisfied` checks only that the container is
running, so a re-run will **not** rewrite `traefik.yml` / `docker-compose.yml`
when Traefik is already up. This matches the existing "skip if present" semantics
used throughout `setup` and will be documented. Changing config is a manual
operation (edit the file, `docker compose up -d`) for now.

## Application label cookbook (documentation)

A downstream app opts into routing + HTTPS by joining the `traefik` network and
declaring labels:

```yaml
services:
  myapp:
    image: ghcr.io/example/myapp:latest
    networks: [traefik]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.myapp.rule=Host(`app.example.com`)"
      - "traefik.http.routers.myapp.entrypoints=websecure"
      - "traefik.http.routers.myapp.tls.certresolver=le"
      # if the app listens on a non-80 port:
      - "traefik.http.services.myapp.loadbalancer.server.port=3000"
networks:
  traefik:
    external: true
```

## Testing (TDD)

- `tests/test_traefik_paths.py` — path derivation.
- `tests/test_fs.py` — `write_file` writes content and applies owner/mode.
- `tests/test_docker_cli.py` — `network_exists` / `create_network`.
- `tests/test_docker_compose.py` — `up` invokes `docker compose -f … up -d`,
  raises on failure.
- `tests/test_setup_steps.py` — `TraefikDirsStep`, `TraefikNetworkStep`,
  `TraefikStep` (satisfied/unsatisfied probes; `apply` writes files, creates the
  network, brings the stack up, and sets `TraefikDeployment`; tailnet IP baked
  into the published 8080 binding; `exposedByDefault: false` present).
- `tests/test_setup.py` — `build_steps` includes Traefik steps only when
  `cert_email` is supplied (and an auth key is present).
- `tests/test_cli_setup.py` — `--traefik-cert-email` / `FONFON_TRAEFIK_CERT_EMAIL`
  plumbing reaches `run_setup`.
- `tests/test_setup_output.py` — Traefik deployment panel renders; both sdci and
  Traefik panels appear when both deploy.
- `tests/test_models_setup.py` — `TraefikDeployment` and the widened union.

## Documentation

- New `docs/manual/docs/services/traefik.md` — architecture, the dashboard /
  tailnet model, and the label cookbook above.
- Update `docs/manual/docs/commands/setup.md` — add the three Traefik rows to the
  provisioning-steps table and a note about `--traefik-cert-email`.
- Update `docs/manual/mkdocs.yml` nav with a "Services" section linking the new
  page.

## Version

Bump `pyproject.toml` `0.4.1` → `0.5.0` (minor — new feature).

## Out of scope

- DNS-01 / wildcard certificates and DNS-provider credentials.
- Authenticated (non-`insecure`) dashboard behind a Host router.
- A `fonfon check` probe for Traefik (the existing `DockerService` already
  models an `external_network` fact and could be extended later).
- Rewriting Traefik config on re-run (see Known limitation).
