"""Tests for fonfon.system._run."""

from fonfon.system._run import run


def test_run_missing_binary_returns_127():
    proc = run(["__fonfon_no_such_binary__"])
    assert proc.returncode == 127
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_run_timeout_returns_nonzero_without_raising():
    # `sleep` runs longer than the timeout -> TimeoutExpired must be swallowed
    proc = run(["sleep", "5"], timeout=0.05)
    assert proc.returncode != 0
    assert proc.stdout == ""


def test_run_passes_env_to_subprocess():
    # echo $FONFON_X via env; the child sees the merged env
    proc = run(["sh", "-c", 'printf %s "$FONFON_X"'], env={"FONFON_X": "abc"})
    assert proc.returncode == 0
    assert proc.stdout == "abc"
