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


def _report_with_token():
    return SetupReport(
        steps=[
            StepResult(
                title="sdci config",
                status=SetupStatus.INSTALLED,
                detail="installed",
                token="T" * 42,
            ),
        ]
    )


def _render_summary(report):
    buf = StringIO()
    setup_console.render_summary(
        report, Console(file=buf, force_terminal=False, width=100)
    )
    return buf.getvalue()


def test_console_summary_prints_token_when_present():
    out = _render_summary(_report_with_token())
    assert "sdci token" in out
    assert "T" * 42 in out


def test_console_summary_omits_token_when_absent():
    out = _render_summary(_report())
    assert "sdci token" not in out


def test_json_includes_token_field():
    buf = StringIO()
    setup_json.render(
        _report_with_token(), Console(file=buf, force_terminal=False, width=100)
    )
    data = json_module.loads(buf.getvalue())
    assert data["steps"][0]["token"] == "T" * 42
