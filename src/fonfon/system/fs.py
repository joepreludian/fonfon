"""Boundary adapter for filesystem directory creation."""

import os
from collections.abc import Callable

from fonfon.system._run import run as _default_run


class Fs:
    def __init__(
        self,
        run: Callable = _default_run,
        exists: Callable[[str], bool] = os.path.exists,
    ):
        self._run = run
        self._exists = exists

    def exists(self, path: str) -> bool:
        return self._exists(path)

    def make_dir(self, path: str, owner: str, mode: str) -> None:
        proc = self._run(["install", "-d", "-o", owner, "-g", owner, "-m", mode, path])
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"mkdir {path} failed (rc {proc.returncode}): {detail}")
