"""Boundary adapter for filesystem directory creation and file writes."""

import os
import pathlib
from collections.abc import Callable

from fonfon.system._run import run as _default_run


def _default_write_text(path: str, content: str) -> None:
    pathlib.Path(path).write_text(content)


class Fs:
    def __init__(
        self,
        run: Callable = _default_run,
        exists: Callable[[str], bool] = os.path.exists,
        write_text: Callable[[str, str], None] = _default_write_text,
    ):
        self._run = run
        self._exists = exists
        self._write_text = write_text

    def exists(self, path: str) -> bool:
        return self._exists(path)

    def make_dir(self, path: str, owner: str, mode: str) -> None:
        proc = self._run(["install", "-d", "-o", owner, "-g", owner, "-m", mode, path])
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"install -d {path} failed (rc {proc.returncode}): {detail}"
            )

    def write_file(self, path: str, content: str, owner: str, mode: str) -> None:
        self._write_text(path, content)
        chown = self._run(["chown", f"{owner}:{owner}", path])
        if chown.returncode != 0:
            detail = chown.stderr.strip() or chown.stdout.strip()
            raise RuntimeError(f"chown {path} failed (rc {chown.returncode}): {detail}")
        chmod = self._run(["chmod", mode, path])
        if chmod.returncode != 0:
            detail = chmod.stderr.strip() or chmod.stdout.strip()
            raise RuntimeError(f"chmod {path} failed (rc {chmod.returncode}): {detail}")
