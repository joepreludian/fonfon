"""Tests for setup output renderers (console and json)."""

import json as json_module
from io import StringIO

from rich.console import Console

from fonfon.models_setup import SdciDeployment, SetupReport, SetupStatus, StepResult
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


def _report_with_deployment():
    return SetupReport(
        steps=[
            StepResult(
                title="sdci config",
                status=SetupStatus.INSTALLED,
                detail="installed",
                deployment=SdciDeployment(
                    base_dir="/home/p/services/sdci",
                    tasks_dir="/home/p/services/sdci/tasks",
                    uploads_dir="/home/p/services/sdci/uploads",
                    token="T" * 42,
                ),
            ),
        ]
    )


def _render_summary(report):
    buf = StringIO()
    setup_console.render_summary(
        report, Console(file=buf, force_terminal=False, width=100)
    )
    return buf.getvalue()


def test_console_summary_renders_deployment_panel():
    out = _render_summary(_report_with_deployment())
    assert "sdci-server deployed" in out
    assert "/home/p/services/sdci" in out
    assert "/home/p/services/sdci/tasks" in out
    assert "/home/p/services/sdci/uploads" in out
    assert "T" * 42 in out


def test_console_summary_no_panel_without_deployment():
    out = _render_summary(_report())
    assert "sdci-server deployed" not in out


def test_json_includes_deployment_field():
    buf = StringIO()
    setup_json.render(
        _report_with_deployment(), Console(file=buf, force_terminal=False, width=100)
    )
    data = json_module.loads(buf.getvalue())
    assert data["steps"][0]["deployment"]["token"] == "T" * 42
