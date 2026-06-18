"""Rich renderables for Fonfon's terminal screens."""

from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from fonfon import get_version
from fonfon.logo import CAT_LOGO, ORANGE, ORANGE_BRIGHT, ORANGE_DIM


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
