"""Rich renderables for Fonfon's terminal screens."""

from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fonfon import get_version
from fonfon.logo import CAT_LOGO, ORANGE, ORANGE_BRIGHT, ORANGE_DIM


def build_header(version: str) -> RenderableType:
    """Two-column header: the cat logo beside 'fonfon - vX.Y.Z'."""
    grid = Table.grid(padding=(0, 4))
    grid.add_column()
    grid.add_column(vertical="middle")
    grid.add_row(
        Text(CAT_LOGO, style=ORANGE),
        Text(f"fonfon - v{version}", style=f"bold {ORANGE_BRIGHT}"),
    )
    return grid


def build_action_box(action: str) -> RenderableType:
    """Small panel naming the action being performed."""
    return Panel.fit(
        Text(action, style=f"bold {ORANGE_BRIGHT}"),
        border_style=ORANGE,
    )


def build_usage_hint() -> RenderableType:
    """Panel showing the two primary commands: check and setup."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=f"bold {ORANGE_BRIGHT}")
    grid.add_column(style=ORANGE_DIM)
    grid.add_row("fonfon check", "— inspect system readiness")
    grid.add_row(
        "sudo fonfon setup <user> --tailscale-key <key>",
        "— provision the server",
    )
    grid.add_row(
        "  --github-user <gh>",
        "— harden SSH from GitHub",
    )
    return Panel.fit(grid, border_style=ORANGE, title=Text("Quick start", style=ORANGE))


def build_banner() -> RenderableType:
    """Build the orange hello banner: logo, project name, version, greeting."""
    body = Group(
        Align.center(Text(CAT_LOGO, style=ORANGE)),
        Text(""),
        Align.center(Text(f"Fonfon v{get_version()}", style=f"bold {ORANGE_BRIGHT}")),
        Align.center(Text("Hello, World!", style=ORANGE)),
        Align.center(Text("Opinionated VPS configurator", style=ORANGE_DIM)),
    )
    return Panel.fit(body, border_style=ORANGE, padding=(1, 6))
