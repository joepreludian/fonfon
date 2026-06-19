"""Tests for setup output renderers (console and json)."""

import json as json_module
from io import StringIO

from rich.console import Console

from fonfon.models_setup import SetupReport, SetupStatus, StepResult
from fonfon.output import setup_console, setup_json


def _report():
    return SetupReport(
        steps=[
            StepResult(title="User", status=SetupStatus.INSTALLED, detail="installed"),
            StepResult(title="Docker", status=SetupStatus.FAILED, detail="boom"),
        ]
    )


def _render(renderer):
    buf = StringIO()
    renderer.render(_report(), Console(file=buf, force_terminal=False, width=100))
    return buf.getvalue()


def test_console_lists_steps_and_statuses():
    out = _render(setup_console)
    assert "User" in out and "Docker" in out
    assert "INSTALLED" in out and "FAILED" in out


def test_console_render_includes_action_box():
    out = _render(setup_console)
    assert "setup" in out


def test_json_roundtrips():
    data = json_module.loads(_render(setup_json))
    assert data["steps"][1]["status"] == "failed"


def test_render_step_start_includes_title():
    class _StubStep:
        title = "Docker"

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=100)
    setup_console.render_step_start(_StubStep(), console)
    assert "Docker" in buf.getvalue()
