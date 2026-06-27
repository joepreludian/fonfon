"""Tests for the six concrete SetupStep implementations."""

import pytest

from fonfon.services.sdci_paths import sdci_paths
from fonfon.services.setup_steps import (
    DOCKER_GPG_URL,
    DOCKER_KEYRING,
    DOCKER_PACKAGES,
    DOCKER_REPO_FILE,
    TAILSCALE_INSTALL_URL,
    AuthorizedKeysStep,
    DockerGroupStep,
    DockerStep,
    PipxStep,
    SdciConfigStep,
    SdciDirsStep,
    SdciStep,
    SshHardeningStep,
    TailscaleStep,
    TailscaleUpStep,
    TraefikDirsStep,
    TraefikNetworkStep,
    TraefikStep,
    UserStep,
)
from fonfon.services.ssh_config import SSHD_DROPIN_PATH, render_sshd_hardening
from fonfon.services.ssh_paths import ssh_paths
from fonfon.services.traefik_config import TRAEFIK_IMAGE, TRAEFIK_NETWORK
from fonfon.services.traefik_paths import traefik_paths
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

    def setup(self, ip, token, uploads_dir, tasks_dir, user):
        self.setup_args = (ip, token, uploads_dir, tasks_dir, user)


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


PATHS = sdci_paths("preludian")


def test_sdci_config_satisfied_when_configured():
    step = SdciConfigStep(
        "preludian",
        PATHS,
        tailscale=FakeTailscale(ip="100.64.0.1"),
        sdci=FakeSdci(configured=True),
    )
    assert step.is_satisfied() is True


def test_sdci_config_not_satisfied_when_unconfigured():
    step = SdciConfigStep(
        "preludian",
        PATHS,
        tailscale=FakeTailscale(ip="100.64.0.1"),
        sdci=FakeSdci(configured=False),
    )
    assert step.is_satisfied() is False


def test_sdci_config_apply_configures_and_sets_deployment():
    ts = FakeTailscale(ip="100.64.0.1")
    sdci = FakeSdci()
    step = SdciConfigStep(
        "preludian", PATHS, tailscale=ts, sdci=sdci, token_factory=lambda: "T" * 42
    )
    step.apply()
    assert sdci.setup_args == (
        "100.64.0.1",
        "T" * 42,
        PATHS.uploads,
        PATHS.tasks,
        "preludian",
    )
    assert step.deployment.base_dir == PATHS.base
    assert step.deployment.tasks_dir == PATHS.tasks
    assert step.deployment.uploads_dir == PATHS.uploads
    assert step.deployment.token == "T" * 42


def test_sdci_config_apply_raises_without_ip():
    step = SdciConfigStep(
        "preludian",
        PATHS,
        tailscale=FakeTailscale(ip=None),
        sdci=FakeSdci(),
        token_factory=lambda: "T",
    )
    with pytest.raises(RuntimeError):
        step.apply()


# ── SdciDirsStep ─────────────────────────────────────────────────────────────


class FakeFs:
    def __init__(self, existing=(), contents=None):
        self._existing = set(existing) | set(contents or {})
        self.made = []
        self.writes = []
        self.contents = dict(contents or {})

    def exists(self, path):
        return path in self._existing

    def make_dir(self, path, owner, mode):
        self.made.append((path, owner, mode))
        self._existing.add(path)

    def write_file(self, path, content, owner, mode):
        self.writes.append((path, content, owner, mode))
        self._existing.add(path)
        self.contents[path] = content

    def read_text(self, path):
        return self.contents[path]


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


# ── Traefik steps ──────────────────────────────────────────────────────────────


class FakeDockerCli:
    def __init__(self, networks=(), container=None):
        self._networks = set(networks)
        self._container = container
        self.created = []

    def network_exists(self, name):
        return name in self._networks

    def create_network(self, name):
        self.created.append(name)
        self._networks.add(name)

    def inspect_container(self, name):
        return self._container


class FakeCompose:
    def __init__(self):
        self.upped = []

    def up(self, compose_file):
        self.upped.append(compose_file)


TPATHS = traefik_paths("deploy")


def test_traefik_dirs_satisfied_when_all_exist():
    fs = FakeFs(existing=(TPATHS.base, TPATHS.acme, TPATHS.dynamic))
    assert TraefikDirsStep("deploy", TPATHS, fs=fs).is_satisfied() is True


def test_traefik_dirs_not_satisfied_when_any_missing():
    fs = FakeFs(existing=(TPATHS.base, TPATHS.acme))
    assert TraefikDirsStep("deploy", TPATHS, fs=fs).is_satisfied() is False


def test_traefik_dirs_apply_creates_base_acme_dynamic_0700():
    fs = FakeFs()
    TraefikDirsStep("deploy", TPATHS, fs=fs).apply()
    assert fs.made == [
        (TPATHS.base, "deploy", "0700"),
        (TPATHS.acme, "deploy", "0700"),
        (TPATHS.dynamic, "deploy", "0700"),
    ]


def test_traefik_network_satisfied_when_exists():
    docker = FakeDockerCli(networks=[TRAEFIK_NETWORK])
    assert TraefikNetworkStep(docker=docker).is_satisfied() is True


def test_traefik_network_not_satisfied_when_absent():
    assert TraefikNetworkStep(docker=FakeDockerCli()).is_satisfied() is False


def test_traefik_network_apply_creates_network():
    docker = FakeDockerCli()
    TraefikNetworkStep(docker=docker).apply()
    assert docker.created == [TRAEFIK_NETWORK]


def test_traefik_satisfied_when_container_running():
    docker = FakeDockerCli(container={"State": {"Running": True}})
    step = TraefikStep("deploy", TPATHS, "you@example.com", docker=docker)
    assert step.is_satisfied() is True


def test_traefik_not_satisfied_when_container_absent_or_stopped():
    assert (
        TraefikStep(
            "deploy", TPATHS, "you@example.com", docker=FakeDockerCli(container=None)
        ).is_satisfied()
        is False
    )
    stopped = FakeDockerCli(container={"State": {"Running": False}})
    assert (
        TraefikStep("deploy", TPATHS, "you@example.com", docker=stopped).is_satisfied()
        is False
    )


def test_traefik_apply_writes_files_brings_up_and_sets_deployment():
    fs = FakeFs()
    docker = FakeDockerCli()
    compose = FakeCompose()
    ts = FakeTailscale(ip="100.64.0.1")
    step = TraefikStep(
        "deploy",
        TPATHS,
        "you@example.com",
        tailscale=ts,
        docker=docker,
        compose=compose,
        fs=fs,
    )
    step.apply()

    # static config written to traefik.yml, compose to docker-compose.yml, 0644
    written = {path: (content, owner, mode) for path, content, owner, mode in fs.writes}
    assert TPATHS.static_config in written
    assert TPATHS.compose_file in written
    assert written[TPATHS.static_config][1:] == ("deploy", "0644")
    assert written[TPATHS.compose_file][1:] == ("deploy", "0644")
    # compose content pins the image and binds the dashboard to the tailnet IP
    assert TRAEFIK_IMAGE in written[TPATHS.compose_file][0]
    assert "100.64.0.1:8080:8080" in written[TPATHS.compose_file][0]
    # static config disables expose-by-default and carries the cert email
    assert "exposedByDefault: false" in written[TPATHS.static_config][0]
    assert "you@example.com" in written[TPATHS.static_config][0]
    # stack brought up
    assert compose.upped == [TPATHS.compose_file]
    # deployment surfaced
    assert step.deployment.network == TRAEFIK_NETWORK
    assert step.deployment.compose_file == TPATHS.compose_file
    assert step.deployment.dashboard_url == "http://100.64.0.1:8080/dashboard/"
    assert step.deployment.cert_email == "you@example.com"


def test_traefik_apply_raises_without_ip():
    step = TraefikStep(
        "deploy",
        TPATHS,
        "you@example.com",
        tailscale=FakeTailscale(ip=None),
        docker=FakeDockerCli(),
        compose=FakeCompose(),
        fs=FakeFs(),
    )
    with pytest.raises(RuntimeError):
        step.apply()


# ── SSH steps ───────────────────────────────────────────────────────────────────


class FakeGitHubKeys:
    def __init__(self, keys=(), error=None):
        self._keys = list(keys)
        self._error = error
        self.fetched = []

    def fetch(self, username):
        self.fetched.append(username)
        if self._error is not None:
            raise self._error
        return list(self._keys)


SPATHS = ssh_paths("deploy")


def test_authorized_keys_satisfied_when_file_exists():
    fs = FakeFs(existing=(SPATHS.authorized_keys,))
    step = AuthorizedKeysStep("deploy", "octocat", SPATHS, fs=fs)
    assert step.is_satisfied() is True


def test_authorized_keys_not_satisfied_when_absent():
    step = AuthorizedKeysStep("deploy", "octocat", SPATHS, fs=FakeFs())
    assert step.is_satisfied() is False


def test_authorized_keys_apply_fetches_and_writes():
    fs = FakeFs()
    gh = FakeGitHubKeys(keys=["ssh-ed25519 AAA", "ssh-rsa BBB"])
    AuthorizedKeysStep("deploy", "octocat", SPATHS, github=gh, fs=fs).apply()

    assert gh.fetched == ["octocat"]
    # .ssh dir created 0700, owned by the operator
    assert (SPATHS.ssh_dir, "deploy", "0700") in fs.made
    # authorized_keys written 0600, owned by the operator, with both keys + header
    written = {path: (content, owner, mode) for path, content, owner, mode in fs.writes}
    assert SPATHS.authorized_keys in written
    content, owner, mode = written[SPATHS.authorized_keys]
    assert (owner, mode) == ("deploy", "0600")
    assert "ssh-ed25519 AAA" in content
    assert "ssh-rsa BBB" in content
    assert "github.com/octocat" in content


def test_authorized_keys_apply_raises_and_writes_nothing_when_no_keys():
    fs = FakeFs()
    step = AuthorizedKeysStep(
        "deploy", "ghost", SPATHS, github=FakeGitHubKeys(keys=[]), fs=fs
    )
    with pytest.raises(RuntimeError, match="no public SSH keys"):
        step.apply()
    assert fs.writes == []


def test_ssh_hardening_not_satisfied_when_dropin_absent():
    step = SshHardeningStep("deploy", "octocat", SPATHS, fs=FakeFs())
    assert step.is_satisfied() is False


def test_ssh_hardening_satisfied_when_content_matches():
    fs = FakeFs(contents={SSHD_DROPIN_PATH: render_sshd_hardening()})
    assert SshHardeningStep("deploy", "octocat", SPATHS, fs=fs).is_satisfied() is True


def test_ssh_hardening_not_satisfied_when_content_drifts():
    fs = FakeFs(contents={SSHD_DROPIN_PATH: "PermitRootLogin yes\n"})
    assert SshHardeningStep("deploy", "octocat", SPATHS, fs=fs).is_satisfied() is False


def test_ssh_hardening_apply_refuses_without_authorized_keys():
    # lockout guard: no authorized_keys present -> refuse, write nothing
    fs = FakeFs()
    step = SshHardeningStep("deploy", "octocat", SPATHS, fs=fs)
    with pytest.raises(RuntimeError, match="lock you out"):
        step.apply()
    assert fs.writes == []


def test_ssh_hardening_apply_writes_dropin_and_sets_deployment():
    fs = FakeFs(existing=(SPATHS.authorized_keys,))
    step = SshHardeningStep("deploy", "octocat", SPATHS, fs=fs)
    step.apply()

    written = {path: (content, owner, mode) for path, content, owner, mode in fs.writes}
    assert SSHD_DROPIN_PATH in written
    content, owner, mode = written[SSHD_DROPIN_PATH]
    assert (owner, mode) == ("root", "0644")
    assert content == render_sshd_hardening()
    # deployment surfaced for the reload advisory
    assert step.deployment.dropin_file == SSHD_DROPIN_PATH
    assert step.deployment.authorized_keys == SPATHS.authorized_keys
    assert step.deployment.github_user == "octocat"
    assert "reload" in step.deployment.reload_hint
