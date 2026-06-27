"""The bare `fonfon` command prints the hello banner and exits cleanly."""

from click.testing import CliRunner

from fonfon import get_version
from fonfon.cli import main


def test_cli_exits_successfully():
    result = CliRunner().invoke(main)
    assert result.exit_code == 0


def test_cli_shows_project_name():
    result = CliRunner().invoke(main)
    assert "Fonfon" in result.output


def test_cli_shows_version():
    result = CliRunner().invoke(main)
    assert get_version() in result.output


def test_cli_shows_hello_world():
    result = CliRunner().invoke(main)
    assert "Hello, World!" in result.output


def test_cli_shows_usage_hints():
    result = CliRunner().invoke(main)
    assert "fonfon check" in result.output
    assert "sudo fonfon setup" in result.output
