"""Tests for the `fonfon setup` CLI command."""

import json as json_module

from click.testing import CliRunner

from fonfon.cli import main
from fonfon.models_setup import SetupReport, SetupStatus, StepResult

_KEY = ["--tailscale-key", "tskey-test"]


def _ok_report():
    return SetupReport(steps=[StepResult(title="User", status=SetupStatus.SKIPPED)])


def _patch_run_setup(monkeypatch, report):
    monkeypatch.setattr(
        "fonfon.cli.run_setup",
        lambda u, k, run=None, on_step_start=None, on_result=None: report,
    )


def test_setup_requires_root(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 1000)
    result = CliRunner().invoke(main, ["setup", "jon", *_KEY])
    assert result.exit_code != 0
    assert "root" in result.output.lower()


def test_setup_requires_auth_key(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    called = {"ran": False}

    def _spy(*args, **kwargs):
        called["ran"] = True
        return _ok_report()

    monkeypatch.setattr("fonfon.cli.run_setup", _spy)
    result = CliRunner().invoke(
        main, ["setup", "jon"], env={"FONFON_TAILSCALE_KEY": ""}
    )
    assert result.exit_code == 1
    assert "auth key" in result.output.lower()
    assert "login.tailscale.com" in result.output
    assert called["ran"] is False


def test_setup_runs_as_root_exit_zero(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    _patch_run_setup(monkeypatch, _ok_report())
    result = CliRunner().invoke(main, ["setup", "jon", *_KEY])
    assert result.exit_code == 0


def test_setup_exit_one_on_failure(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    failed = SetupReport(steps=[StepResult(title="Docker", status=SetupStatus.FAILED)])
    _patch_run_setup(monkeypatch, failed)
    result = CliRunner().invoke(main, ["setup", "jon", *_KEY])
    assert result.exit_code == 1


def test_setup_json(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    _patch_run_setup(monkeypatch, _ok_report())
    result = CliRunner().invoke(main, ["setup", "jon", "--output", "json", *_KEY])
    assert json_module.loads(result.output)["steps"][0]["status"] == "skipped"


def test_setup_accepts_key_from_env(monkeypatch):
    monkeypatch.setattr("fonfon.cli.os.geteuid", lambda: 0)
    _patch_run_setup(monkeypatch, _ok_report())
    result = CliRunner().invoke(
        main, ["setup", "jon"], env={"FONFON_TAILSCALE_KEY": "tskey-env"}
    )
    assert result.exit_code == 0
