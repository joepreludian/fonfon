"""Tests for the `fonfon check` CLI command."""

import json as json_module

from click.testing import CliRunner

from fonfon.cli import main
from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus


def _patch_report(monkeypatch, *statuses):
    items = [
        CheckItem(key=f"k{i}", label=f"L{i}", status=s, detail="d")
        for i, s in enumerate(statuses)
    ]
    report = CheckReport(sections=[CheckSection(title="S", items=items)])
    monkeypatch.setattr("fonfon.cli.run_check", lambda: report)


def test_check_exits_zero_when_all_ok(monkeypatch):
    _patch_report(monkeypatch, CheckStatus.OK, CheckStatus.INFO)
    result = CliRunner().invoke(main, ["check"])
    assert result.exit_code == 0


def test_check_exits_one_on_failure(monkeypatch):
    _patch_report(monkeypatch, CheckStatus.FAIL)
    result = CliRunner().invoke(main, ["check"])
    assert result.exit_code == 1


def test_check_json_output_parses(monkeypatch):
    _patch_report(monkeypatch, CheckStatus.OK)
    result = CliRunner().invoke(main, ["check", "--output", "json"])
    data = json_module.loads(result.output)
    assert data["sections"][0]["items"][0]["status"] == "ok"
