"""The hello banner shows the logo, project name, version, and greeting."""

import io

from rich.console import Console

from fonfon import get_version
from fonfon.logo import CAT_LOGO
from fonfon.ui import build_action_box, build_banner, build_usage_hint


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


def test_action_box_renders_and_contains_action_label():
    out = _render(build_action_box("check"))
    assert "check" in out


def test_action_box_renders_setup_label():
    out = _render(build_action_box("setup"))
    assert "setup" in out


def test_usage_hint_shows_check_and_setup_commands():
    out = _render(build_usage_hint())
    assert "fonfon check" in out
    assert "sudo fonfon setup" in out
