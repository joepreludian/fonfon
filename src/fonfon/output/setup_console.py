"""Console renderer for SetupReport — rich colored output with header and summary."""

from rich.console import Console

from fonfon import get_version
from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.services.setup_steps import SetupStep
from fonfon.ui import build_action_box, build_header

_STYLE: dict[SetupStatus, tuple[str, str]] = {
    SetupStatus.INSTALLED: ("green", "✓ INSTALLED"),
    SetupStatus.SKIPPED: ("dim", "– SKIPPED"),
    SetupStatus.FAILED: ("red", "✗ FAILED"),
}


def render_header(console: Console) -> None:
    """Print the Fonfon banner/header."""
    console.print(build_header(get_version()))


def render_action(console: Console) -> None:
    """Print the action box for the setup command."""
    console.print(build_action_box("setup"))


def render_step_start(step: SetupStep, console: Console) -> None:
    """Print a header line for a step immediately before its output streams."""
    console.print(f"[bold orange1]{step.title}[/bold orange1]")


def render_step(result: StepResult, console: Console) -> None:
    """Print a single step result line."""
    style, label = _STYLE[result.status]
    detail = result.detail or ""
    console.print(f"  {result.title:<14} [{style}]{label}[/{style}]  {detail}")


def render_summary(report: SetupReport, console: Console) -> None:
    """Print the counts footer."""
    installed = sum(1 for s in report.steps if s.status is SetupStatus.INSTALLED)
    skipped = sum(1 for s in report.steps if s.status is SetupStatus.SKIPPED)
    failed = sum(1 for s in report.steps if s.status is SetupStatus.FAILED)
    console.print(
        f"[green]{installed} installed[/green] · "
        f"[dim]{skipped} skipped[/dim] · "
        f"[red]{failed} failed[/red]"
    )


def render(report: SetupReport, console: Console) -> None:
    """Print header, action box, step lines, and a summary footer."""
    render_header(console)
    render_action(console)
    for result in report.steps:
        render_step(result, console)
    render_summary(report, console)
