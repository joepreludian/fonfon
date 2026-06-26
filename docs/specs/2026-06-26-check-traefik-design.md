# Traefik posture in `fonfon check` — design

**Date:** 2026-06-26
**Status:** Approved (pending spec review)
**Topic:** Extend the **Docker** section of `fonfon check` to report Traefik's
posture: container running, the `traefik` network created, ports 80/443
published, and the dashboard listening **only** on the tailnet.

## Summary

`fonfon check`'s Docker section already reports three facts about Traefik
(container running, ports 80/443, a network heuristic). This change makes the
Docker section the read-only mirror of what `setup` provisions, with four items:

| Item | Status logic |
|------|--------------|
| **traefik** (container) | `OK` running · `WARN` not running |
| **network** (`traefik`) | `OK` the named external network exists · `WARN` not created |
| **ports 80/443** | `OK` both published · `WARN` not |
| **dashboard (tailnet-only)** | `OK` 8080 bound to the host's tailnet IP only · **`FAIL` exposed publicly (0.0.0.0)** · `WARN` not running / not published / tailnet IP unknown |

Two refinements vs. today:

1. The network item now checks the **actual named `traefik` network**
   (`docker network inspect traefik`) instead of the previous "is the container
   attached to a non-default network" heuristic.
2. A **new dashboard item** verifies the management/API port (8080) is bound to
   the host's Tailscale IP and **not** to a public address.

## Decisions

Settled during brainstorming:

1. **"Only on tailscale" detection:** compare the 8080 binding's `HostIp` to the
   host's **actual tailnet IP**, which `check` already reads from the
   `tailscale0` interface in the Network section. The dashboard is "tailnet-only"
   iff it has at least one 8080 binding and **every** 8080 binding's `HostIp`
   equals that tailnet IP. If tailscale isn't up (no tailnet IP), the item is
   `WARN` ("tailnet IP unknown").
2. **Public exposure severity:** if any 8080 binding is to `0.0.0.0` / `::` / ""
   (all-interfaces), the item is **`FAIL`** — a publicly reachable dashboard
   defeats the tailnet-only model, so it fails the check gate (non-zero exit).
   This only triggers when Traefik is actually running and misconfigured; a
   fresh/no-Traefik box stays `WARN`.
3. **Network item** is the named `traefik` network's existence (replaces the
   old `external_network` heuristic, which is removed).

## Architecture

Unchanged layering: `DockerCli` (boundary, already has `network_exists` /
`inspect_container`) → `DockerService` (facts, no policy) → `check.run_check` /
`build_report` (status policy) → `output/console.py` + `output/json.py`
(rendering). No new adapter is needed.

### `DockerCli`

No change — `inspect_container(name)` and `network_exists(name)` already exist
(the latter was added with the Traefik setup feature).

### `DockerReport` (facts)

`services/docker_service.py` — remove `external_network` / `_DEFAULT_NETWORKS`,
add:

```python
class DockerReport(BaseModel):
    docker_installed: bool
    service: str | None = None
    present: bool = False
    host: str | None = None
    listening: dict[int, bool] = Field(default_factory=dict)
    network_name: str | None = None        # which external network was checked
    network_present: bool = False          # `docker network inspect <name>` ok
    dashboard_port: int | None = None
    dashboard_tailnet_only: bool = False   # 8080 bound only to the tailnet IP
    dashboard_public: bool = False         # 8080 bound to 0.0.0.0/::/""
    tailnet_ip: str | None = None          # expected tailnet IP (for detail)
```

### `DockerService.ensure_listening` (facts, no policy)

Gains keyword params and computes the new facts. The named-network check runs
**even when the container is absent** (the network can exist without it):

```python
def ensure_listening(
    self,
    host: str,
    ports: list[int],
    *,
    network: str | None = None,
    dashboard_port: int | None = None,
    tailnet_ip: str | None = None,
) -> DockerReport:
    if not self._docker.is_available():
        return DockerReport(docker_installed=False, service=self._service, host=host,
                            listening={p: False for p in ports},
                            network_name=network, dashboard_port=dashboard_port,
                            tailnet_ip=tailnet_ip)
    network_present = self._docker.network_exists(network) if network else False
    inspect = self._docker.inspect_container(self._service)
    if inspect is None:
        return DockerReport(docker_installed=True, service=self._service, present=False,
                            host=host, listening={p: False for p in ports},
                            network_name=network, network_present=network_present,
                            dashboard_port=dashboard_port, tailnet_ip=tailnet_ip)
    published = (inspect.get("NetworkSettings", {}) or {}).get("Ports") or {}
    listening = {
        port: any(
            b.get("HostPort") == str(port) and b.get("HostIp") in (host, "0.0.0.0")
            for b in (published.get(f"{port}/tcp") or [])
        )
        for port in ports
    }
    dashboard_public = False
    dashboard_tailnet_only = False
    if dashboard_port is not None:
        binds = published.get(f"{dashboard_port}/tcp") or []
        host_ips = [b.get("HostIp") for b in binds]
        dashboard_public = any(ip in {"0.0.0.0", "::", ""} for ip in host_ips)
        dashboard_tailnet_only = (
            bool(binds)
            and tailnet_ip is not None
            and all(ip == tailnet_ip for ip in host_ips)
        )
    return DockerReport(
        docker_installed=True, service=self._service, present=True, host=host,
        listening=listening, network_name=network, network_present=network_present,
        dashboard_port=dashboard_port, dashboard_public=dashboard_public,
        dashboard_tailnet_only=dashboard_tailnet_only, tailnet_ip=tailnet_ip,
    )
```

### Policy (`check._docker_section`)

Produces the four items. The dashboard item is the only one that can `FAIL`:

```python
def _dashboard_item(docker):
    port = docker.dashboard_port
    if not docker.present:
        status, detail = CheckStatus.WARN, "container not running"
    elif docker.dashboard_public:
        status, detail = CheckStatus.FAIL, f"exposed publicly (0.0.0.0:{port})"
    elif docker.dashboard_tailnet_only:
        status, detail = CheckStatus.OK, f"tailnet-only ({docker.tailnet_ip}:{port})"
    elif docker.tailnet_ip is None:
        status, detail = CheckStatus.WARN, "tailnet IP unknown (is tailscale up?)"
    else:
        status, detail = CheckStatus.WARN, "not published on tailnet"
    return CheckItem(key="docker.dashboard", label="dashboard (tailnet-only)",
                     status=status, detail=detail)
```

The network item: `OK`/`WARN` on `network_present`, label `"network"`, detail
`"'traefik' created"` / `"'traefik' not created"` (from `network_name`). The
container and ports items keep their existing logic.

### `run_check` wiring

```python
from fonfon.services.traefik_config import TRAEFIK_NETWORK

TRAEFIK_PORTS = [80, 443]
TRAEFIK_DASHBOARD_PORT = 8080
TAILSCALE_IFACE = "tailscale0"

network = NetworkService().get_ips()
tailnet_ip = network.interfaces.get(TAILSCALE_IFACE)
docker = (
    DockerService()
    .for_service("traefik")
    .ensure_listening(
        host="0.0.0.0",
        ports=TRAEFIK_PORTS,
        network=TRAEFIK_NETWORK,
        dashboard_port=TRAEFIK_DASHBOARD_PORT,
        tailnet_ip=tailnet_ip,
    )
)
```

`network` is already computed before `docker` in `run_check`, so the tailnet IP
is available to pass in — no extra call and no new dependency on the Tailscale
adapter.

## Output

- **Console** (`output/console.py`) renders sections generically, so the new
  4-item Docker section appears automatically; no renderer change needed. A
  `FAIL` dashboard turns the row red and flips the summary footer to
  "✗ N failed".
- **JSON** (`output/json.py`) dumps the whole report; the new `CheckItem`s and
  the widened `DockerReport` serialise automatically.

## Edge cases

- **Docker not installed** → existing SKIP section, unchanged.
- **Container absent but network exists** → network item `OK`, container/ports/
  dashboard `WARN`. (The network check runs independently of the container.)
- **Tailscale down** (no `tailscale0` IP) → `tailnet_ip` is `None`; a published
  dashboard that isn't public reports `WARN` "tailnet IP unknown" (we can't
  prove it's the *right* tailnet address).
- **Dashboard bound to both tailnet and 0.0.0.0** → `dashboard_public` wins →
  `FAIL`.
- **IPv6 `::` all-interfaces bind** counts as public.

## Documentation

- Update `docs/manual/docs/commands/check.md`: the Docker row in the "What it
  checks" table (four items) and a note that a **publicly-exposed Traefik
  dashboard fails the check**.

## Version

Bump `pyproject.toml` by one **minor** (new check capability). At time of writing
the version is `0.5.1`; if the SSH-hardening feature lands first it will be
`0.6.0`, so this becomes `0.7.0`. The final task bumps to the next minor over
whatever is current.

## Out of scope

- Verifying Traefik's *config file* contents (`exposedByDefault`, the ACME
  resolver) — `check` inspects runtime/Docker facts only.
- Checking certificate issuance / `acme.json`.
- A heuristic CGNAT-range fallback when the tailnet IP is unknown (we chose exact
  IP matching).

## Testing (TDD)

- `tests/test_docker_service.py` — `network_present` from `network_exists`
  (true/false; checked even when the container is absent); `dashboard_tailnet_only`
  (bound to the tailnet IP), `dashboard_public` (0.0.0.0), neither when the IP is
  unknown or 8080 is unpublished. `FakeDocker` gains a `network_exists`.
- `tests/test_check.py` — the four-item Docker section: network `OK`/`WARN`;
  dashboard `OK` (tailnet-only) / `FAIL` (public) / `WARN` (not running); the
  all-OK and all-WARN paths over the new fields.
