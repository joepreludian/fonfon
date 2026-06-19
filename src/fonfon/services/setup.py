"""The `setup` use-case: run provisioning steps with continue-on-error."""

from collections.abc import Callable

from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.services.setup_steps import (
    DockerGroupStep,
    DockerStep,
    PipxStep,
    SdciStep,
    SetupStep,
    TailscaleStep,
    UserStep,
)


def build_steps(new_user: str) -> list[SetupStep]:
    """Return the six provisioning steps in execution order."""
    return [
        UserStep(new_user),
        DockerStep(),
        DockerGroupStep(new_user),
        TailscaleStep(),
        PipxStep(),
        SdciStep(),
    ]


def run_step(step: SetupStep) -> StepResult:
    """Apply the continue-on-error policy for a single step."""
    if step.is_satisfied():
        return StepResult(
            title=step.title, status=SetupStatus.SKIPPED, detail="already present"
        )
    try:
        step.apply()
        return StepResult(
            title=step.title, status=SetupStatus.INSTALLED, detail="installed"
        )
    except Exception as exc:  # noqa: BLE001 — continue-on-error by design
        return StepResult(title=step.title, status=SetupStatus.FAILED, detail=str(exc))


def run_setup(
    new_user: str, on_result: Callable[[StepResult], None] | None = None
) -> SetupReport:
    """Run all provisioning steps and return the aggregated report."""
    results = []
    for step in build_steps(new_user):
        result = run_step(step)
        if on_result is not None:
            on_result(result)
        results.append(result)
    return SetupReport(steps=results)
