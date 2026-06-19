"""The `setup` use-case: run provisioning steps with continue-on-error."""

from collections.abc import Callable

from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.services.setup_steps import (
    DockerGroupStep,
    DockerStep,
    PipxStep,
    SdciConfigStep,
    SdciStep,
    SetupStep,
    TailscaleStep,
    TailscaleUpStep,
    UserStep,
)
from fonfon.system._run import run as _default_run
from fonfon.system.apt import Apt
from fonfon.system.dpkg import Dpkg
from fonfon.system.pipx import Pipx
from fonfon.system.sdci import Sdci
from fonfon.system.tailscale import Tailscale
from fonfon.system.users import Users


def build_steps(
    new_user: str, auth_key: str | None = None, run: Callable = _default_run
) -> list[SetupStep]:
    """Return the provisioning steps in execution order.

    The two service-configuration steps are appended only when an auth key is
    supplied (the CLI requires one; calling without it yields install-only steps).
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
        steps.append(TailscaleUpStep(auth_key, tailscale=Tailscale(run=run)))
        steps.append(SdciConfigStep(tailscale=Tailscale(run=run), sdci=Sdci(run=run)))
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
            token=step.token,
        )
    except Exception as exc:  # noqa: BLE001 — continue-on-error by design
        return StepResult(title=step.title, status=SetupStatus.FAILED, detail=str(exc))


def run_setup(
    new_user: str,
    auth_key: str | None = None,
    *,
    run: Callable = _default_run,
    on_step_start: Callable[[SetupStep], None] | None = None,
    on_result: Callable[[StepResult], None] | None = None,
) -> SetupReport:
    """Run all provisioning steps and return the aggregated report."""
    results = []
    for step in build_steps(new_user, auth_key, run=run):
        if on_step_start is not None:
            on_step_start(step)
        result = run_step(step)
        if on_result is not None:
            on_result(result)
        results.append(result)
    return SetupReport(steps=results)
