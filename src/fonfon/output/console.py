"""Console renderer for CheckReport — rich colored table with header and summary."""

from rich.console import Console
from rich.table import Table

from fonfon import get_version
from fonfon.logo import ORANGE_BRIGHT
from fonfon.models import CheckReport, CheckStatus
from fonfon.ui import build_header

_STYLE: dict[CheckStatus, tuple[str, str]] = {
    CheckStatus.OK: ("green", "✓ OK"),
    CheckStatus.WARN: ("yellow", "! WARN"),
    CheckStatus.FAIL: ("red", "✗ FAIL"),
    CheckStatus.INFO: ("cyan", "• INFO"),
    CheckStatus.SKIP: ("dim", "– SKIP"),
}


def render(report: CheckReport, console: Console) -> None:
    """Print header, grouped status table, and a pass/fail summary footer."""
    console.print(build_header(get_version()))
    table = Table(show_header=True, header_style=f"bold {ORANGE_BRIGHT}", expand=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for section in report.sections:
        table.add_section()
        table.add_row(f"[bold]{section.title}[/bold]", "", "")
        for item in section.items:
            style, label = _STYLE[item.status]
            table.add_row(
                f"  {item.label}",
                f"[{style}]{label}[/{style}]",
                item.detail or "",
            )
    console.print(table)
    fails = sum(
        1 for s in report.sections for i in s.items if i.status is CheckStatus.FAIL
    )
    warns = sum(
        1 for s in report.sections for i in s.items if i.status is CheckStatus.WARN
    )
    if report.ok:
        console.print(f"[green]✓ all checks passed[/green] · {warns} warnings")
    else:
        console.print(
            f"[red]✗ {fails} failed[/red] · {warns} warnings — checks did not pass"
        )
