"""The `setup` use-case: run provisioning steps with continue-on-error."""

from collections.abc import Callable

from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.services.sdci_paths import sdci_paths
from fonfon.services.setup_steps import (
    AuthorizedKeysStep,
    DockerGroupStep,
    DockerStep,
    PipxStep,
    SdciConfigStep,
    SdciDirsStep,
    SdciStep,
    SetupStep,
    SshHardeningStep,
    TailscaleStep,
    TailscaleUpStep,
    TraefikDirsStep,
    TraefikNetworkStep,
    TraefikStep,
    UserStep,
)
from fonfon.services.ssh_paths import ssh_paths
from fonfon.services.traefik_paths import traefik_paths
from fonfon.system._run import run as _default_run
from fonfon.system.apt import Apt
from fonfon.system.docker_cli import DockerCli
from fonfon.system.docker_compose import DockerCompose
from fonfon.system.dpkg import Dpkg
from fonfon.system.fs import Fs
from fonfon.system.github_keys import GitHubKeys
from fonfon.system.pipx import Pipx
from fonfon.system.sdci import Sdci
from fonfon.system.tailscale import Tailscale
from fonfon.system.users import Users


def build_steps(
    new_user: str,
    auth_key: str | None = None,
    cert_email: str | None = None,
    github_user: str | None = None,
    run: Callable = _default_run,
) -> list[SetupStep]:
    """Return the provisioning steps in execution order.

    The sdci steps are appended only when an auth key is supplied; the Traefik
    steps only when both an auth key and a cert email are supplied. The SSH
    hardening steps are appended last, only when a GitHub user is supplied
    (independent of the auth key — hardening needs only the operator account).
    """
    steps: list[SetupStep] = [
        UserStep(new_user, users=Users(run=run)),
        DockerStep(apt=Apt(run=run), dpkg=Dpkg(run=run), run=run),
        DockerGroupStep(new_user, users=Users(run=run)),
        TailscaleStep(dpkg=Dpkg(run=run), run=run),
        PipxStep(apt=Apt(run=run), dpkg=Dpkg(run=run)),
        SdciStep(pipx=Pipx(run=run)),
    ]
    if auth_key:
        paths = sdci_paths(new_user)
        steps.append(TailscaleUpStep(auth_key, tailscale=Tailscale(run=run)))
        steps.append(SdciDirsStep(new_user, paths, fs=Fs(run=run)))
        steps.append(
            SdciConfigStep(
                new_user,
                paths,
                tailscale=Tailscale(run=run),
                sdci=Sdci(run=run),
            )
        )
        if cert_email:
            tpaths = traefik_paths(new_user)
            steps.append(TraefikDirsStep(new_user, tpaths, fs=Fs(run=run)))
            steps.append(TraefikNetworkStep(docker=DockerCli(run=run)))
            steps.append(
                TraefikStep(
                    new_user,
                    tpaths,
                    cert_email,
                    tailscale=Tailscale(run=run),
                    docker=DockerCli(run=run),
                    compose=DockerCompose(run=run),
                    fs=Fs(run=run),
                )
            )
    if github_user:
        spaths = ssh_paths(new_user)
        steps.append(
            AuthorizedKeysStep(
                new_user, github_user, spaths, github=GitHubKeys(), fs=Fs(run=run)
            )
        )
        steps.append(SshHardeningStep(new_user, github_user, spaths, fs=Fs(run=run)))
    return steps


def run_step(step: SetupStep) -> StepResult:
    """Apply the continue-on-error policy for a single step."""
    if step.is_satisfied():
        return StepResult(
            title=step.title, status=SetupStatus.SKIPPED, detail="already present"
        )
    try:
        step.apply()
        return StepResult(
            title=step.title,
            status=SetupStatus.INSTALLED,
            detail="installed",
            deployment=step.deployment,
        )
    except Exception as exc:  # noqa: BLE001 — continue-on-error by design
        return StepResult(title=step.title, status=SetupStatus.FAILED, detail=str(exc))


def run_setup(
    new_user: str,
    auth_key: str | None = None,
    cert_email: str | None = None,
    github_user: str | None = None,
    *,
    run: Callable = _default_run,
    on_step_start: Callable[[SetupStep], None] | None = None,
    on_result: Callable[[StepResult], None] | None = None,
) -> SetupReport:
    """Run all provisioning steps and return the aggregated report."""
    results = []
    for step in build_steps(new_user, auth_key, cert_email, github_user, run=run):
        if on_step_start is not None:
            on_step_start(step)
        result = run_step(step)
        if on_result is not None:
            on_result(result)
        results.append(result)
    return SetupReport(steps=results)
