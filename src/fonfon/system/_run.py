import os
import subprocess

DEFAULT_TIMEOUT = 10


def run(
    args: list[str],
    timeout: int = DEFAULT_TIMEOUT,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run a command, capturing text output; never raises on non-zero exit,
    a missing binary (rc 127), or a timeout (rc 1)."""
    merged = {**os.environ, **env} if env else None
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=merged,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr="")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")
