"""Tests for the streaming command runner."""

from io import StringIO

from rich.console import Console

from fonfon.system.streaming import run_streamed


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=False, width=100)


def test_success_returncode_and_stdout():
    console = _console()
    result = run_streamed(["sh", "-c", "printf 'alpha\\nbeta\\n'"], console)
    assert result.returncode == 0
    assert "alpha" in result.stdout
    assert "beta" in result.stdout


def test_success_output_written_to_console():
    console = _console()
    run_streamed(["sh", "-c", "printf 'alpha\\nbeta\\n'"], console)
    output = console.file.getvalue()
    assert "alpha" in output
    assert "beta" in output


def test_failure_returncode():
    console = _console()
    result = run_streamed(["sh", "-c", "exit 3"], console)
    assert result.returncode == 3


def test_missing_binary_returns_127():
    console = _console()
    result = run_streamed(["__fonfon_nope__"], console)
    assert result.returncode == 127


def test_timeout_kills_process():
    console = _console()
    result = run_streamed(["sleep", "5"], console, timeout=1)
    assert result.returncode != 0
