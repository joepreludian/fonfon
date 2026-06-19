"""The concrete provisioning steps for `fonfon setup`."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from fonfon.system import probes
from fonfon.system._run import run as _default_run
from fonfon.system.apt import Apt
from fonfon.system.dpkg import Dpkg
from fonfon.system.pipx import Pipx
from fonfon.system.users import Users

SDCI_PACKAGE = "sdci"
SDCI_EXECUTABLE = "sdci-server"

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
