"""Tests for the `fonfon setup` CLI command."""

import json as json_module

from click.testing import CliRunner

from fonfon.cli import main
from fonfon.models_setup import SetupReport, SetupStatus, StepResult


def _ok_report():
    return SetupReport(steps=[StepResult(title="User", status=SetupStatus.SKIPPED)])


def test_setup_requires_root(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 1000)
    result = CliRunner().invoke(main, ["setup", "jon"])
    assert result.exit_code != 0
    assert "root" in result.output.lower()


def test_setup_runs_as_root_exit_zero(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    monkeypatch.setattr(
        "fonfon.cli.run_setup",
        lambda u, run=None, on_step_start=None, on_result=None: _ok_report(),
    )
    result = CliRunner().invoke(main, ["setup", "jon"])
    assert result.exit_code == 0


def test_setup_exit_one_on_failure(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    failed = SetupReport(steps=[StepResult(title="Docker", status=SetupStatus.FAILED)])
    monkeypatch.setattr(
        "fonfon.cli.run_setup",
        lambda u, run=None, on_step_start=None, on_result=None: failed,
    )
    result = CliRunner().invoke(main, ["setup", "jon"])
    assert result.exit_code == 1


def test_setup_json(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    monkeypatch.setattr(
        "fonfon.cli.run_setup",
        lambda u, run=None, on_step_start=None, on_result=None: _ok_report(),
    )
    result = CliRunner().invoke(main, ["setup", "jon", "--output", "json"])
    assert json_module.loads(result.output)["steps"][0]["status"] == "skipped"
