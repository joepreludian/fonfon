"""Tests for the output renderers (console and json)."""

import json as json_module
from io import StringIO

from rich.console import Console

from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus
from fonfon.output import console as console_renderer
from fonfon.output import json as json_renderer


def _report():
    return CheckReport(
        sections=[
            CheckSection(
                title="Packages",
                items=[
                    CheckItem(
                        key="package.sudo",
                        label="sudo",
                        status=CheckStatus.OK,
                        detail="1.9",
                    ),
                    CheckItem(
                        key="package.docker-ce",
                        label="docker-ce",
                        status=CheckStatus.FAIL,
                        detail="not installed",
                    ),
                ],
            )
        ]
    )


def _render(renderer):
    buffer = StringIO()
    renderer.render(_report(), Console(file=buffer, force_terminal=False, width=100))
    return buffer.getvalue()


def test_console_render_includes_labels_and_section():
    out = _render(console_renderer)
    assert "Packages" in out
    assert "sudo" in out and "docker-ce" in out
    assert "FAIL" in out
    assert "OK" in out


def test_console_render_includes_action_box():
    out = _render(console_renderer)
    assert "check" in out


def test_json_render_is_valid_and_roundtrips():
    out = _render(json_renderer)
    data = json_module.loads(out)
    assert data["sections"][0]["items"][0]["status"] == "ok"
