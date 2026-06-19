"""Console renderer for SetupReport — rich colored output with header and summary."""

from rich.console import Console

from fonfon import get_version
from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.ui import build_header

_STYLE: dict[SetupStatus, tuple[str, str]] = {
    SetupStatus.INSTALLED: ("green", "✓ INSTALLED"),
    SetupStatus.SKIPPED: ("dim", "– SKIPPED"),
    SetupStatus.FAILED: ("red", "✗ FAILED"),
}


def render_header(console: Console) -> None:
    """Print the Fonfon banner/header."""
    console.print(build_header(get_version()))


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
    """Print header, step lines, and a summary footer."""
    render_header(console)
    for result in report.steps:
        render_step(result, console)
    render_summary(report, console)
