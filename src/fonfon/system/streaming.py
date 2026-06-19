"""Streaming command runner: pipes output to a rich console live while capturing it."""

import os
import subprocess
import threading

from rich.console import Console

from fonfon.system._run import DEFAULT_TIMEOUT


def run_streamed(
    args: list[str],
    console: Console,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run a command, streaming lines to *console* (dim style) while capturing them.

    A reader thread is used so a hung command still honours the timeout.
    Never raises; returns returncode 127 for missing binary, 1 for timeout.
    """
    merged = {**os.environ, **env} if env else None
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=merged,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", "")

    lines: list[str] = []

    def _reader() -> None:
        # proc.stdout is always set because stdout=subprocess.PIPE was passed above
        for line in proc.stdout:  # type: ignore[union-attr]
            lines.append(line)
            console.print(line.rstrip("\n"), style="dim", highlight=False)

    reader = threading.Thread(target=_reader)
    reader.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        timed_out = True
    reader.join()
    proc.stdout.close()  # type: ignore[union-attr]  # prevent ResourceWarning; fully drained by _reader
    proc.wait()  # reap (idempotent on success path; reaps the killed process)
    rc = 1 if timed_out else proc.returncode
    return subprocess.CompletedProcess(args, rc, "".join(lines), "")
