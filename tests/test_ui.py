"""The hello banner shows the logo, project name, version, and greeting."""

import io

from rich.console import Console

from fonfon import get_version
from fonfon.logo import CAT_LOGO
from fonfon.ui import build_banner


def _render(renderable) -> str:
    console = Console(width=80, file=io.StringIO(), color_system=None)
    console.print(renderable)
    return console.file.getvalue()


def test_banner_includes_project_name():
    assert "Fonfon" in _render(build_banner())


def test_banner_includes_version():
    assert get_version() in _render(build_banner())


def test_banner_includes_hello_world():
    assert "Hello, World!" in _render(build_banner())


def test_banner_includes_cat_logo():
    first_logo_line = CAT_LOGO.splitlines()[0].strip()
    assert first_logo_line in _render(build_banner())
