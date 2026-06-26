"""The concrete provisioning steps for `fonfon setup`."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from fonfon.models_setup import SdciDeployment, TraefikDeployment
from fonfon.services.sdci_paths import SdciPaths
from fonfon.services.token import generate_token
from fonfon.services.traefik_config import (
    TRAEFIK_NETWORK,
    render_compose,
    render_static_config,
)
from fonfon.services.traefik_paths import TraefikPaths
from fonfon.system import probes
from fonfon.system._run import run as _default_run
from fonfon.system.apt import Apt
from fonfon.system.docker_cli import DockerCli
from fonfon.system.docker_compose import DockerCompose
from fonfon.system.dpkg import Dpkg
from fonfon.system.fs import Fs
from fonfon.system.pipx import Pipx
from fonfon.system.sdci import Sdci
from fonfon.system.tailscale import Tailscale
from fonfon.system.users import Users

SDCI_PACKAGE = "sdci"
SDCI_EXECUTABLE = "sdci-server"
SDCI_DIR_MODE = "0700"

TRAEFIK_DIR_MODE = "0700"
TRAEFIK_FILE_MODE = "0644"

DOCKER_PACKAGES = [
    "docker-ce",
    "docker-ce-cli",
    "containerd.io",
    "docker-buildx-plugin",
    "docker-compose-plugin",
]
TAILSCALE_INSTALL_URL = "https://tailscale.com/install.sh"
DOCKER_GPG_URL = "https://download.docker.com/linux/debian/gpg"
DOCKER_KEYRING = "/etc/apt/keyrings/docker.asc"
DOCKER_REPO_FILE = "/etc/apt/sources.list.d/docker.list"


class SetupStep(ABC):
    """Base class for an idempotent provisioning action."""

    title: str
    deployment: SdciDeployment | TraefikDeployment | None = (
        None  # set by steps that deploy a service
    )

    @abstractmethod
    def is_satisfied(self) -> bool:
        """Return True if this step is already in the desired state."""

    @abstractmethod
    def apply(self) -> None:
        """Perform the mutation; raise on failure."""


class UserStep(SetupStep):
    """Ensure the operator user exists and belongs to sudo."""

    title = "User"

    def __init__(self, user: str, users: Users | None = None) -> None:
        self._user = user
        self._users = users or Users()

    def is_satisfied(self) -> bool:
        return self._users.exists(self._user) and self._users.in_group(
            self._user, "sudo"
        )

    def apply(self) -> None:
        if not self._users.exists(self._user):
            self._users.create(self._user)
        self._users.add_to_group(self._user, "sudo")


class DockerStep(SetupStep):
    """Install Docker CE via the official apt repository."""

    title = "Docker"

    def __init__(
        self,
        apt: Apt | None = None,
        dpkg: Dpkg | None = None,
        read_os_release: Callable = probes.read_os_release,
        run: Callable = _default_run,
    ) -> None:
        self._apt = apt or Apt()
        self._dpkg = dpkg or Dpkg()
        self._read_os_release = read_os_release
        self._run = run

    def is_satisfied(self) -> bool:
        return self._dpkg.query("docker-ce").installed

    def apply(self) -> None:
        self._apt.install("ca-certificates", "curl")
        self._apt.add_keyring(DOCKER_GPG_URL, DOCKER_KEYRING)
        arch = self._run(["dpkg", "--print-architecture"]).stdout.strip()
        codename = self._read_os_release().get("VERSION_CODENAME", "")
        if not codename:
            raise RuntimeError(
                "VERSION_CODENAME not found in /etc/os-release; "
                "cannot configure Docker apt repo"
            )
        repo = (
            f"deb [arch={arch} signed-by={DOCKER_KEYRING}] "
            f"https://download.docker.com/linux/debian {codename} stable\n"
        )
        self._apt.add_repo(repo, DOCKER_REPO_FILE)
        self._apt.update()
        self._apt.install(*DOCKER_PACKAGES)


class DockerGroupStep(SetupStep):
    """Add the operator user to the docker group."""

    title = "Docker group"

    def __init__(self, user: str, users: Users | None = None) -> None:
        self._user = user
        self._users = users or Users()

    def is_satisfied(self) -> bool:
        return self._users.in_group(self._user, "docker")

    def apply(self) -> None:
        self._users.add_to_group(self._user, "docker")


class TailscaleStep(SetupStep):
    """Install Tailscale via the official install script."""

    title = "Tailscale"

    def __init__(self, dpkg: Dpkg | None = None, run: Callable = _default_run) -> None:
        self._dpkg = dpkg or Dpkg()
        self._run = run

    def is_satisfied(self) -> bool:
        return self._dpkg.query("tailscale").installed

    def apply(self) -> None:
        proc = self._run(
            ["sh", "-c", f"curl -fsSL {TAILSCALE_INSTALL_URL} | sh"],
            timeout=600,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"tailscale install failed: {detail}")


class PipxStep(SetupStep):
    """Install pipx via apt."""

    title = "pipx"

    def __init__(self, apt: Apt | None = None, dpkg: Dpkg | None = None) -> None:
        self._apt = apt or Apt()
        self._dpkg = dpkg or Dpkg()

    def is_satisfied(self) -> bool:
        return self._dpkg.query("pipx").installed

    def apply(self) -> None:
        self._apt.update()
        self._apt.install("pipx")


class SdciStep(SetupStep):
    """Install sdci globally via pipx."""

    title = "sdci"

    def __init__(self, pipx: Pipx | None = None) -> None:
        self._pipx = pipx or Pipx()

    def is_satisfied(self) -> bool:
        return self._pipx.has_executable(SDCI_EXECUTABLE)

    def apply(self) -> None:
        self._pipx.install_global(SDCI_PACKAGE)


class TailscaleUpStep(SetupStep):
    """Join the tailnet with an auth key."""

    title = "Tailscale up"

    def __init__(self, auth_key: str, tailscale: Tailscale | None = None) -> None:
        self._auth_key = auth_key
        self._tailscale = tailscale or Tailscale()

    def is_satisfied(self) -> bool:
        return self._tailscale.ipv4() is not None

    def apply(self) -> None:
        self._tailscale.up(self._auth_key)


class SdciConfigStep(SetupStep):
    """Configure sdci-server against the tailnet IP with a generated token."""

    title = "sdci config"

    def __init__(
        self,
        user: str,
        paths: SdciPaths,
        tailscale: Tailscale | None = None,
        sdci: Sdci | None = None,
        token_factory: Callable[[], str] = generate_token,
    ) -> None:
        self._user = user
        self._paths = paths
        self._tailscale = tailscale or Tailscale()
        self._sdci = sdci or Sdci()
        self._token_factory = token_factory

    def is_satisfied(self) -> bool:
        return self._sdci.is_configured()

    def apply(self) -> None:
        ip = self._tailscale.ipv4()
        if ip is None:
            raise RuntimeError(
                "no Tailscale IPv4 available; is `tailscale up` complete?"
            )
        token = self._token_factory()
        self._sdci.setup(ip, token, self._paths.uploads, self._paths.tasks, self._user)
        self.deployment = SdciDeployment(
            base_dir=self._paths.base,
            tasks_dir=self._paths.tasks,
            uploads_dir=self._paths.uploads,
            token=token,
        )


class SdciDirsStep(SetupStep):
    """Create the operator's sdci service directories (tasks, uploads)."""

    title = "sdci dirs"

    def __init__(self, user: str, paths: SdciPaths, fs: Fs | None = None) -> None:
        self._user = user
        self._paths = paths
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        return self._fs.exists(self._paths.tasks) and self._fs.exists(
            self._paths.uploads
        )

    def apply(self) -> None:
        for path in (self._paths.base, self._paths.tasks, self._paths.uploads):
            self._fs.make_dir(path, self._user, SDCI_DIR_MODE)


class TraefikDirsStep(SetupStep):
    """Create the operator's Traefik service directories (base, acme, dynamic)."""

    title = "Traefik dirs"

    def __init__(self, user: str, paths: TraefikPaths, fs: Fs | None = None) -> None:
        self._user = user
        self._paths = paths
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        return (
            self._fs.exists(self._paths.base)
            and self._fs.exists(self._paths.acme)
            and self._fs.exists(self._paths.dynamic)
        )

    def apply(self) -> None:
        for path in (self._paths.base, self._paths.acme, self._paths.dynamic):
            self._fs.make_dir(path, self._user, TRAEFIK_DIR_MODE)


class TraefikNetworkStep(SetupStep):
    """Create the external `traefik` Docker network."""

    title = "Traefik network"

    def __init__(self, docker: DockerCli | None = None) -> None:
        self._docker = docker or DockerCli()

    def is_satisfied(self) -> bool:
        return self._docker.network_exists(TRAEFIK_NETWORK)

    def apply(self) -> None:
        self._docker.create_network(TRAEFIK_NETWORK)


class TraefikStep(SetupStep):
    """Write Traefik's config + compose file and bring the stack up."""

    title = "Traefik"

    def __init__(
        self,
        user: str,
        paths: TraefikPaths,
        cert_email: str,
        tailscale: Tailscale | None = None,
        docker: DockerCli | None = None,
        compose: DockerCompose | None = None,
        fs: Fs | None = None,
    ) -> None:
        self._user = user
        self._paths = paths
        self._cert_email = cert_email
        self._tailscale = tailscale or Tailscale()
        self._docker = docker or DockerCli()
        self._compose = compose or DockerCompose()
        self._fs = fs or Fs()

    def is_satisfied(self) -> bool:
        inspect = self._docker.inspect_container("traefik")
        return bool(inspect and inspect.get("State", {}).get("Running"))

    def apply(self) -> None:
        ip = self._tailscale.ipv4()
        if ip is None:
            raise RuntimeError(
                "no Tailscale IPv4 available; is `tailscale up` complete?"
            )
        self._fs.write_file(
            self._paths.static_config,
            render_static_config(self._cert_email),
            self._user,
            TRAEFIK_FILE_MODE,
        )
        self._fs.write_file(
            self._paths.compose_file,
            render_compose(ip, self._paths),
            self._user,
            TRAEFIK_FILE_MODE,
        )
        self._compose.up(self._paths.compose_file)
        self.deployment = TraefikDeployment(
            compose_file=self._paths.compose_file,
            network=TRAEFIK_NETWORK,
            dashboard_url=f"http://{ip}:8080/dashboard/",
            cert_email=self._cert_email,
        )
