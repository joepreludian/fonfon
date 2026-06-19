import subprocess

DEFAULT_TIMEOUT = 10


def run(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a command capturing output.

    Never raises on non-zero exit, on a missing binary (FileNotFoundError),
    or on a hung command that exceeds *timeout* seconds (TimeoutExpired).

    Return codes:
      127 — binary not found (follows shell convention).
        1 — command timed out (distinct from 127 to keep meanings separate).
    """
    try:
        return subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=timeout
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr="")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")
