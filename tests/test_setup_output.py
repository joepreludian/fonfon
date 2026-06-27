"""Tests for setup output renderers (console and json)."""

import json as json_module
from io import StringIO

from rich.console import Console

from fonfon.models_setup import (
    SdciDeployment,
    SetupReport,
    SetupStatus,
    SshDeployment,
    StepResult,
    TraefikDeployment,
)
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


def _report_with_traefik():
    return SetupReport(
        steps=[
            StepResult(
                title="Traefik",
                status=SetupStatus.INSTALLED,
                detail="installed",
                deployment=TraefikDeployment(
                    compose_file="/home/p/services/traefik/docker-compose.yml",
                    network="traefik",
                    dashboard_url="http://100.64.0.1:8080/dashboard/",
                    cert_email="you@example.com",
                ),
            ),
        ]
    )


def test_console_summary_renders_traefik_panel():
    out = _render_summary(_report_with_traefik())
    assert "Traefik deployed" in out
    assert "/home/p/services/traefik/docker-compose.yml" in out
    assert "traefik" in out
    assert "http://100.64.0.1:8080/dashboard/" in out
    assert "you@example.com" in out


def test_console_summary_renders_both_panels():
    report = SetupReport(
        steps=_report_with_deployment().steps + _report_with_traefik().steps
    )
    out = _render_summary(report)
    assert "sdci-server deployed" in out
    assert "Traefik deployed" in out


def _report_with_ssh():
    return SetupReport(
        steps=[
            StepResult(
                title="SSH hardening",
                status=SetupStatus.INSTALLED,
                detail="installed",
                deployment=SshDeployment(
                    dropin_file="/etc/ssh/sshd_config.d/99-fonfon-hardening.conf",
                    authorized_keys="/home/p/.ssh/authorized_keys",
                    github_user="octocat",
                    reload_hint="sudo systemctl reload ssh",
                ),
            ),
        ]
    )


def test_console_summary_renders_ssh_panel_and_reload_advice():
    out = _render_summary(_report_with_ssh())
    assert "SSH hardened" in out
    assert "octocat" in out
    assert "/home/p/.ssh/authorized_keys" in out
    assert "99-fonfon-hardening.conf" in out
    assert "Reload SSH" in out
    assert "systemctl reload ssh" in out


def test_console_summary_no_ssh_panel_without_deployment():
    out = _render_summary(_report())
    assert "SSH hardened" not in out
    assert "Reload SSH" not in out
