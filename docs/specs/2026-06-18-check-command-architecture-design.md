# `fonfon check` & the Layered Application Architecture — Design

- **Date:** 2026-06-18
- **Status:** Approved (design); not yet implemented
- **Topic:** Fonfon's layered input/service/output architecture, and the first
  feature command built on it — `fonfon check`, a read-only system readiness
  report.

## Context & motivation

Fonfon is an opinionated VPS configurator. Before it provisions anything, it
needs to *report* what a target box already has — which distro and architecture
it is, which packages and systemd services are present, what its addresses are,
and whether Docker is already running a reverse proxy. That report is the
`fonfon check` command.

`check` is also the vehicle for establishing Fonfon's **layered architecture**,
which every later command will reuse:

- **Input** — the CLI (`click`), which parses arguments and selects an output
  format.
- **Service layer** — fluent, reusable *domain services* that probe one area of
  the system each and return plain-fact DTOs. No presentation, no policy.
- **Use-case layer** — a per-command function that composes the domain services
  and applies *policy* (what counts as OK / WARN / FAIL), producing a single
  presentation DTO.
- **Output** — renderers that consume the presentation DTO and emit either a
  rich console screen or JSON.

The DTO is the contract between logic and presentation: the service layer
produces it, and the output mechanism either serializes it (JSON) or draws a
screen from it (console).

## Goals

- Ship `fonfon check`: a read-only report of system readiness.
- Establish the layered architecture (input → services → use-case → output) that
  later commands reuse.
- Make every layer unit-testable without a real VPS, via injected boundary
  adapters.
- Support both `--output console` (rich, colored) and `--output json`.

## Non-goals

- Performing any provisioning or mutation. `check` only reads.
- Supporting non-Debian package managers now. The package layer uses a Strategy
  pattern so RHEL/rpm and others can be added later, but only Debian (dpkg) ships
  in this iteration.
- Joining a Tailscale tailnet or any network mutation.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| systemd access | Shell out to `systemctl` via a thin adapter | Zero extra deps, no C extensions, keeps the PEX scie self-contained. `pysystemd` is LGPLv3, sporadically maintained, and only wraps `systemctl` anyway. |
| pydantic | **Runtime** dependency | DTOs and `--output json` serialization run inside the shipped binary, not just in tests. |
| Public IP | Best-effort external lookup | Query a public echo endpoint (stdlib `urllib`) with a short timeout; show `unknown` if unreachable. Local IPs always resolve offline. |
| Exit code | Non-zero iff any item is `FAIL` | Makes `check` usable as a CI / provisioning gate. `WARN`/`INFO`/`SKIP` keep exit 0. |
| Service structure | Fluent per-area domain services | Each area is encapsulated, reusable beyond `check`, and independently testable. |
| Package detection | Strategy pattern keyed on distro | Package management is the distro-variant axis (dpkg vs rpm). Debian-only now; extensible by registry. |
| Two DTO layers | Domain DTOs (facts) + `CheckReport` (presentation) | Keeps services policy-free and reusable; concentrates check policy in one place. |

## Architecture

### Module layout

```
src/fonfon/
  __init__.py            # get_version()                                  (existing)
  cli.py                 # click group + `check`; --output; wires use-case -> renderer
  logo.py                # CAT_LOGO + orange palette                      (existing)
  ui.py                  # shared rich pieces: banner + header(logo | "fonfon - vX.Y.Z")
  models.py              # presentation DTOs: CheckStatus, CheckItem, CheckSection, CheckReport
  services/
    os_service.py        # OSService        + OSInfo
    package_service.py   # PackageService   + PackageReport / PackageState
    package_backends.py  # PackageBackend (ABC), DebianPackageBackend, select_package_backend()
    systemd_service.py   # SystemdService   + ServicesReport / ServiceState
    network_service.py   # NetworkService   + NetworkInfo
    docker_service.py    # DockerService    + DockerReport
    check.py             # run_check(): composes services, applies policy -> CheckReport
  system/                # injectable boundary adapters — the ONLY code that does real I/O
    systemctl.py         # Systemctl: is_enabled / is_active / exists
    docker_cli.py        # DockerCli: ps / inspect / network_ls
    dpkg.py              # Dpkg: query a package's status + version
    probes.py            # read_os_release, machine, interfaces (ip -json addr), public_ip (urllib)
  output/
    console.py           # render(report, console): rich header + grouped table
    json.py              # render(report): print(report.model_dump_json(indent=2))
```

The service layer never touches the system directly. All I/O lives in `system/`
boundary adapters, which are injected into services and backends — that is the
test seam.

### Domain services (facts only — no status, no policy)

Each service is **constructed → chained fluently → terminal verb → domain DTO**.

```python
# os_service.py
class OSInfo(BaseModel):
    distro: str          # PRETTY_NAME, e.g. "Debian GNU/Linux 12 (bookworm)"
    distro_id: str       # ID, e.g. "debian"
    architecture: str    # "x86_64" | "aarch64"
OSService().get_info() -> OSInfo

# package_service.py
class PackageState(BaseModel):
    name: str; installed: bool; version: str | None
class PackageReport(BaseModel):
    packages: list[PackageState]
PackageService(backend).for_packages(["sudo","docker-ce","tailscale","python3-pipx"]).ensure_installed() -> PackageReport

# systemd_service.py
class ServiceState(BaseModel):
    name: str; present: bool; enabled: bool; active: bool
class ServicesReport(BaseModel):
    services: list[ServiceState]
SystemdService().for_services(["docker","ssh","tailscaled"]).get_status() -> ServicesReport

# network_service.py
class NetworkInfo(BaseModel):
    interfaces: dict[str, str]   # {"eth0":"203.0.113.5","tailscale0":"100.101.102.103"}
    public_ip: str | None        # best-effort; None when unreachable
NetworkService().get_ips() -> NetworkInfo

# docker_service.py  (degrades gracefully when docker is absent)
class DockerReport(BaseModel):
    docker_installed: bool
    service: str | None              # "traefik"
    present: bool                    # container exists / running
    host: str | None                 # "0.0.0.0"
    listening: dict[int, bool]       # {80: True, 443: True}
    external_network: bool           # attached to a user-defined (non-default) network
DockerService().for_service("traefik").ensure_listening(host="0.0.0.0", ports=[80,443]) -> DockerReport
```

### Package detection — Strategy by distro

`PackageService` is the fluent front; the actual probe is delegated to a
`PackageBackend` strategy chosen from the distro ID.

```python
# services/package_backends.py
class PackageBackend(ABC):
    @abstractmethod
    def query(self, name: str) -> PackageState: ...      # installed + version

class DebianPackageBackend(PackageBackend):              # dpkg family
    def __init__(self, dpkg: Dpkg | None = None):
        self._dpkg = dpkg or Dpkg()                      # boundary adapter -> injectable
    def query(self, name) -> PackageState: ...           # dpkg-query -W -f='${Status} ${Version}'

class UnsupportedDistroError(Exception): ...

_REGISTRY = {"debian": DebianPackageBackend,
             "ubuntu": DebianPackageBackend,
             "raspbian": DebianPackageBackend}           # rpm/RHEL slots in here later

def select_package_backend(distro_id: str) -> PackageBackend:
    cls = _REGISTRY.get(distro_id.lower())
    if cls is None:
        raise UnsupportedDistroError(distro_id)
    return cls()
```

`package_backends.py` is one file now; it graduates to a `package_backends/`
package when a second backend lands. Strategy applies to packages only —
`systemd` and `docker` are distro-agnostic.

### Use-case & policy: `run_check()`

`run_check()` is the only place that applies policy. It composes the services,
then maps their domain DTOs to a `CheckReport`.

```python
def run_check() -> CheckReport:
    os_info = OSService().get_info()
    services = SystemdService().for_services(["docker","ssh","tailscaled"]).get_status()
    network  = NetworkService().get_ips()
    docker   = DockerService().for_service("traefik").ensure_listening(host="0.0.0.0", ports=[80,443])
    try:
        backend  = select_package_backend(os_info.distro_id)
        packages = PackageService(backend).for_packages(
            ["sudo","docker-ce","tailscale","python3-pipx"]).ensure_installed()
    except UnsupportedDistroError:
        packages = None    # -> Packages section becomes a single SKIP row
    return build_report(os_info, packages, services, network, docker)
```

### Presentation DTO & status policy

```python
class CheckStatus(str, Enum):
    OK = "ok"; WARN = "warn"; FAIL = "fail"; INFO = "info"; SKIP = "skip"

class CheckItem(BaseModel):
    key: str            # stable machine id, e.g. "package.docker-ce"
    label: str          # human label
    status: CheckStatus
    detail: str | None  # value / message

class CheckSection(BaseModel):
    title: str
    items: list[CheckItem]

class CheckReport(BaseModel):
    sections: list[CheckSection]
    @property
    def ok(self) -> bool:
        return not any(i.status is CheckStatus.FAIL
                       for s in self.sections for i in s.items)
```

| Section | Items | Status policy |
|---|---|---|
| System | distro, architecture | always `INFO` |
| Packages | sudo, docker-ce, tailscale, python3-pipx | installed → `OK` (detail=version); missing → `FAIL`. Unsupported distro → whole section one `SKIP` row. |
| Services | docker, ssh, tailscaled | enabled → `OK` (detail notes active state); disabled/absent → `FAIL` |
| Network | each interface, public | always `INFO`; public shows `unknown` when unreachable |
| Docker | traefik present, :80/:443 listening, external network | docker absent → whole section `SKIP`. Present → `OK`; gaps → `WARN` (advisory, never `FAIL`) |

**Exit code:** `ctx.exit(0 if report.ok else 1)` — non-zero iff any `FAIL`.

### Output

`-o/--output [console|json]`, default `console`.

**Console** — a two-column header (logo │ title) reusing the existing palette,
then one grouped table; status cells colored and glyphed; a summary footer
mirrors the exit code.

```
        /\_/\
       ( o.o )         fonfon — v0.1.0
      >(  ^  )<
        )   (
       ( --- )
        `---'~

  ┏━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
  ┃ Check          ┃ Status ┃ Detail                          ┃
  ┡━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
  │ System                                                    │
  │  Distro        │ • INFO │ Debian GNU/Linux 12 (bookworm)  │
  │  Architecture  │ • INFO │ x86_64                          │
  │ Packages                                                  │
  │  sudo          │ ✓ OK   │ 1.9.13p3                        │
  │  docker-ce     │ ✗ FAIL │ not installed                   │
  │  tailscale     │ ✓ OK   │ 1.66.4                          │
  │  python3-pipx  │ ✗ FAIL │ not installed                   │
  │ Services                                                  │
  │  docker        │ ✗ FAIL │ not enabled                     │
  │  ssh           │ ✓ OK   │ enabled, active                 │
  │  tailscaled    │ ✓ OK   │ enabled, active                 │
  │ Network                                                   │
  │  eth0          │ • INFO │ 203.0.113.5                     │
  │  tailscale0    │ • INFO │ 100.101.102.103                 │
  │  public        │ • INFO │ 203.0.113.5                     │
  │ Docker                                                    │
  │  traefik       │ ! WARN │ container not running           │
  │  :80 / :443    │ ! WARN │ not listening                   │
  │  ext. network  │ ! WARN │ none attached                   │
  └────────────────┴────────┴─────────────────────────────────┘

  ✗ 3 failed · 4 warnings — checks did not pass          (exit 1)
```

Color map: `OK` green · `WARN` yellow · `FAIL` red · `INFO` cyan · `SKIP` dim.

**JSON** — `print(report.model_dump_json(indent=2))`. JSON and table are 1:1; the
exit code is still set, so JSON consumers can gate on either the payload or `$?`.

## Testing strategy (TDD throughout)

| Layer | How it's tested |
|---|---|
| Boundary adapters | Thin; covered indirectly and via focused tests where they parse output (e.g. `Dpkg` status parsing). |
| Package backends | `DebianPackageBackend(dpkg=FakeDpkg(...))` → assert `PackageState`. |
| Domain services | Inject fakes (`FakeSystemctl`, `FakeDockerCli`, `FakeBackend`, fake probes) → assert the domain DTO. No real system. |
| `check` policy | Feed crafted domain DTOs → assert `CheckReport` statuses + `.ok`, including the unsupported-distro `SKIP` path. |
| Renderers | JSON: parse output, assert structure. Console: render to a recording `Console`, assert labels/statuses present (substring-level, not pixel-exact). |
| CLI | `CliRunner` with a stubbed `run_check` returning a known report → assert exit code (0 vs 1) and format. |
| Integration | One `@pytest.mark.integration` smoke assertion added to the existing Lima harness: `fonfon check` runs and exits on a real Debian guest. |

## Dependencies & system assumptions

- **Add `pydantic>=2` to `[project].dependencies`** (runtime — bundled into the scie).
- **No new Python deps** otherwise: public-IP via stdlib `urllib.request` with a
  short timeout, not `requests`.
- **Target-side binaries** (runtime assumptions, present on Debian; not Python
  deps): `systemctl`, `dpkg-query`, `ip` (iproute2), `docker`.

## Docs & conventions

- **Manual entry** (required by CLAUDE.md): add `docs/manual/docs/commands/check.md`
  and a nav entry in `mkdocs.yml`.
- **CLAUDE.md**: add an *Architecture* section documenting the layering (CLI →
  fluent domain services returning fact DTOs → `check` use-case applies policy →
  `CheckReport` → console/json renderers; `system/` boundary adapters +
  constructor-injection test seam; runtime deps click/rich/pydantic).
- Implementation is TDD via subagents. **No auto-commits** — commits are
  authored and authorized by the maintainer, conventional-commit style, no Claude
  co-author, `pre-commit` run first.

## Content caveats (intentional, not blocking)

1. **Package names are dpkg names** at the call site: `docker-ce` (not the
   transitional `docker`), `python3-pipx`. Revisit if Fonfon installs Docker via
   a different package (`docker.io`).
2. **Interfaces** via `ip -json addr show` — structured parsing rather than
   regex; iproute2 is present on Debian.
3. **"External network"** = traefik attached to a user-defined (non-default)
   network — a pragmatic heuristic, since "external" is really a compose concept.

## Open items / future

- Add RHEL/rpm (and others) as `PackageBackend` subclasses + registry entries.
- Map non-Debian distro IDs (e.g. fedora, rocky) once their backends exist.
- Richer Docker assertions (traefik routing/labels) as provisioning lands.
- `check` will be re-run after `provision` to confirm convergence.
