"""Tests for the six concrete SetupStep implementations."""

import pytest

from fonfon.services.sdci_paths import sdci_paths
from fonfon.services.setup_steps import (
    DOCKER_GPG_URL,
    DOCKER_KEYRING,
    DOCKER_PACKAGES,
    DOCKER_REPO_FILE,
    TAILSCALE_INSTALL_URL,
    DockerGroupStep,
    DockerStep,
    PipxStep,
    SdciConfigStep,
    SdciDirsStep,
    SdciStep,
    TailscaleStep,
    TailscaleUpStep,
    UserStep,
)
from fonfon.system.dpkg import PackageState
from tests.fakes import completed

# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeUsers:
    def __init__(self, existing=(), groups=None):
        self.existing = set(existing)
        self.groups = groups or {}
        self.calls = []

    def exists(self, u):
        return u in self.existing

    def in_group(self, u, g):
        return g in self.groups.get(u, [])

    def create(self, u):
        self.calls.append(("create", u))
        self.existing.add(u)

    def add_to_group(self, u, g):
        self.calls.append(("add", u, g))
        self.groups.setdefault(u, []).append(g)


class FakeDpkg:
    def __init__(self, installed_packages=()):
        self._installed = set(installed_packages)

    def query(self, name):
        return PackageState(name=name, installed=name in self._installed)


class FakeApt:
    def __init__(self):
        self.calls = []

    def install(self, *packages):
        self.calls.append(("install", list(packages)))

    def update(self):
        self.calls.append(("update",))

    def add_keyring(self, url, dest):
        self.calls.append(("add_keyring", url, dest))

    def add_repo(self, content, dest):
        self.calls.append(("add_repo", content, dest))


class FakePipx:
    def __init__(self, installed=()):
        self._installed = set(installed)
        self.calls = []

    def has_executable(self, executable):
        return executable in self._installed

    def install_global(self, package):
        self.calls.append(("install_global", package))


# ── UserStep ──────────────────────────────────────────────────────────────────


def test_user_step_satisfied_when_exists_and_in_sudo():
    users = FakeUsers(existing=["jon"], groups={"jon": ["sudo"]})
    assert UserStep("jon", users=users).is_satisfied() is True


def test_user_step_not_satisfied_when_not_in_sudo():
    users = FakeUsers(existing=["jon"])
    assert UserStep("jon", users=users).is_satisfied() is False


def test_user_step_not_satisfied_when_missing():
    users = FakeUsers()
    assert UserStep("jon", users=users).is_satisfied() is False


def test_user_step_apply_creates_and_adds_sudo():
    users = FakeUsers()
    UserStep("jon", users=users).apply()
    assert ("create", "jon") in users.calls
    assert ("add", "jon", "sudo") in users.calls


def test_user_step_apply_skips_create_when_user_exists():
    users = FakeUsers(existing=["jon"])
    UserStep("jon", users=users).apply()
    assert ("create", "jon") not in users.calls
    assert ("add", "jon", "sudo") in users.calls


# ── DockerStep ────────────────────────────────────────────────────────────────


def test_docker_step_satisfied_when_docker_ce_installed():
    dpkg = FakeDpkg(installed_packages=["docker-ce"])
    assert DockerStep(dpkg=dpkg).is_satisfied() is True


def test_docker_step_not_satisfied_when_not_installed():
    dpkg = FakeDpkg()
    assert DockerStep(dpkg=dpkg).is_satisfied() is False


def test_docker_step_apply_installs_prereqs_keyring_repo_and_packages():
    apt = FakeApt()
    dpkg = FakeDpkg()

    def fake_run(args, timeout=10, env=None):
        if args == ["dpkg", "--print-architecture"]:
            return completed(args, 0, "amd64\n")
        return completed(args, 0, "")

    def fake_os_release():
        return {"VERSION_CODENAME": "bookworm"}

    DockerStep(
        apt=apt, dpkg=dpkg, read_os_release=fake_os_release, run=fake_run
    ).apply()

    install_calls = [c for c in apt.calls if c[0] == "install"]
    # First install: prerequisite packages
    assert install_calls[0][1] == ["ca-certificates", "curl"]
    # Last install: full docker package set
    assert install_calls[-1][1] == list(DOCKER_PACKAGES)

    # add_keyring called with the Docker GPG URL and keyring path
    keyring_calls = [c for c in apt.calls if c[0] == "add_keyring"]
    assert len(keyring_calls) == 1
    assert keyring_calls[0][1] == DOCKER_GPG_URL
    assert keyring_calls[0][2] == DOCKER_KEYRING

    # add_repo: line contains the architecture and codename
    repo_calls = [c for c in apt.calls if c[0] == "add_repo"]
    assert len(repo_calls) == 1
    repo_line, dest = repo_calls[0][1], repo_calls[0][2]
    assert "amd64" in repo_line
    assert "bookworm" in repo_line
    assert dest == DOCKER_REPO_FILE

    # update must be called
    assert ("update",) in apt.calls

    # ordering: add_repo → update → (final) install
    names = [c[0] for c in apt.calls]
    last_install_idx = len(names) - 1 - names[::-1].index("install")
    assert names.index("add_repo") < names.index("update") < last_install_idx


def test_docker_step_apply_raises_when_codename_missing():
    step = DockerStep(
        apt=FakeApt(),
        dpkg=FakeDpkg(),
        read_os_release=lambda: {},  # no VERSION_CODENAME
        run=lambda args, timeout=10, env=None: completed(args, 0, "arm64\n"),
    )
    with pytest.raises(RuntimeError, match="VERSION_CODENAME"):
        step.apply()


# ── DockerGroupStep ───────────────────────────────────────────────────────────


def test_docker_group_step_satisfied_when_in_docker():
    users = FakeUsers(existing=["jon"], groups={"jon": ["docker"]})
    assert DockerGroupStep("jon", users=users).is_satisfied() is True


def test_docker_group_step_not_satisfied_when_not_in_docker():
    users = FakeUsers(existing=["jon"])
    assert DockerGroupStep("jon", users=users).is_satisfied() is False


def test_docker_group_step_apply_adds_docker():
    users = FakeUsers(existing=["jon"])
    DockerGroupStep("jon", users=users).apply()
    assert ("add", "jon", "docker") in users.calls


# ── TailscaleStep ─────────────────────────────────────────────────────────────


def test_tailscale_step_satisfied_when_installed():
    dpkg = FakeDpkg(installed_packages=["tailscale"])
    assert TailscaleStep(dpkg=dpkg).is_satisfied() is True


def test_tailscale_step_not_satisfied_when_not_installed():
    dpkg = FakeDpkg()
    assert TailscaleStep(dpkg=dpkg).is_satisfied() is False


def test_tailscale_step_apply_runs_install_script():
    seen = {}

    def fake_run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    TailscaleStep(dpkg=FakeDpkg(), run=fake_run).apply()
    assert seen["args"][0] == "sh"
    assert TAILSCALE_INSTALL_URL in seen["args"][-1]
    assert seen["timeout"] >= 600


def test_tailscale_step_apply_raises_on_failure():
    def fake_run(args, timeout=10, env=None):
        return completed(args, 1, "", "network error")

    with pytest.raises(RuntimeError):
        TailscaleStep(dpkg=FakeDpkg(), run=fake_run).apply()


# ── PipxStep ──────────────────────────────────────────────────────────────────


def test_pipx_step_satisfied_when_pipx_installed():
    dpkg = FakeDpkg(installed_packages=["pipx"])
    assert PipxStep(dpkg=dpkg).is_satisfied() is True


def test_pipx_step_not_satisfied_when_not_installed():
    dpkg = FakeDpkg()
    assert PipxStep(dpkg=dpkg).is_satisfied() is False


def test_pipx_step_apply_installs_pipx():
    apt = FakeApt()
    PipxStep(apt=apt, dpkg=FakeDpkg()).apply()
    assert ("install", ["pipx"]) in apt.calls


def test_pipx_step_apply_updates_before_install():
    apt = FakeApt()
    PipxStep(apt=apt, dpkg=FakeDpkg()).apply()
    names = [c[0] for c in apt.calls]
    assert names.index("update") < names.index("install")


# ── SdciStep ──────────────────────────────────────────────────────────────────


def test_sdci_step_satisfied_when_sdci_installed():
    pipx = FakePipx(installed=["sdci-server"])
    assert SdciStep(pipx=pipx).is_satisfied() is True


def test_sdci_step_not_satisfied_when_not_installed():
    pipx = FakePipx()
    assert SdciStep(pipx=pipx).is_satisfied() is False


def test_sdci_step_apply_calls_install_global():
    pipx = FakePipx()
    SdciStep(pipx=pipx).apply()
    assert ("install_global", "sdci") in pipx.calls


class FakeTailscale:
    def __init__(self, ip=None):
        self._ip = ip
        self.upped_with = None

    def ipv4(self):
        return self._ip

    def up(self, auth_key):
        self.upped_with = auth_key
        self._ip = "100.64.0.1"


class FakeSdci:
    def __init__(self, configured=False):
        self._configured = configured
        self.setup_args = None

    def is_configured(self):
        return self._configured

    def setup(self, ip, token):
        self.setup_args = (ip, token)


def test_tailscale_up_satisfied_when_ip_present():
    step = TailscaleUpStep("k", tailscale=FakeTailscale(ip="100.64.0.1"))
    assert step.is_satisfied() is True


def test_tailscale_up_not_satisfied_without_ip():
    step = TailscaleUpStep("k", tailscale=FakeTailscale(ip=None))
    assert step.is_satisfied() is False


def test_tailscale_up_apply_calls_up_with_key():
    ts = FakeTailscale(ip=None)
    TailscaleUpStep("tskey-xyz", tailscale=ts).apply()
    assert ts.upped_with == "tskey-xyz"


def test_sdci_config_satisfied_when_configured():
    step = SdciConfigStep(
        tailscale=FakeTailscale(ip="100.64.0.1"), sdci=FakeSdci(configured=True)
    )
    assert step.is_satisfied() is True


def test_sdci_config_not_satisfied_when_unconfigured():
    step = SdciConfigStep(
        tailscale=FakeTailscale(ip="100.64.0.1"), sdci=FakeSdci(configured=False)
    )
    assert step.is_satisfied() is False


def test_sdci_config_apply_configures_with_ip_and_token():
    ts = FakeTailscale(ip="100.64.0.1")
    sdci = FakeSdci()
    step = SdciConfigStep(tailscale=ts, sdci=sdci, token_factory=lambda: "T" * 42)
    step.apply()
    assert sdci.setup_args == ("100.64.0.1", "T" * 42)
    assert step.token == "T" * 42


def test_sdci_config_apply_raises_without_ip():
    step = SdciConfigStep(
        tailscale=FakeTailscale(ip=None), sdci=FakeSdci(), token_factory=lambda: "T"
    )
    with pytest.raises(RuntimeError):
        step.apply()


# ── SdciDirsStep ─────────────────────────────────────────────────────────────


class FakeFs:
    def __init__(self, existing=()):
        self._existing = set(existing)
        self.made = []

    def exists(self, path):
        return path in self._existing

    def make_dir(self, path, owner, mode):
        self.made.append((path, owner, mode))
        self._existing.add(path)


def test_sdci_dirs_satisfied_when_dirs_exist():
    paths = sdci_paths("preludian")
    fs = FakeFs(existing=(paths.tasks, paths.uploads))
    assert SdciDirsStep("preludian", paths, fs=fs).is_satisfied() is True


def test_sdci_dirs_not_satisfied_when_missing():
    paths = sdci_paths("preludian")
    assert SdciDirsStep("preludian", paths, fs=FakeFs()).is_satisfied() is False


def test_sdci_dirs_apply_creates_base_tasks_uploads_owned_0700():
    paths = sdci_paths("preludian")
    fs = FakeFs()
    SdciDirsStep("preludian", paths, fs=fs).apply()
    assert fs.made == [
        (paths.base, "preludian", "0700"),
        (paths.tasks, "preludian", "0700"),
        (paths.uploads, "preludian", "0700"),
    ]
