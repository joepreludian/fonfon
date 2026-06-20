"""Boundary adapter for sdci-server: configure it and detect prior config."""

import os
from collections.abc import Callable

from fonfon.system._run import run as _default_run

SDCI_CONFIG_PATH = "/etc/sdci/config"
SDCI_SETUP_TIMEOUT = 60


class Sdci:
    def __init__(
        self,
        run: Callable = _default_run,
        exists: Callable[[str], bool] = os.path.exists,
    ):
        self._run = run
        self._exists = exists

    def is_configured(self) -> bool:
        return self._exists(SDCI_CONFIG_PATH)

    def setup(
        self, ip: str, token: str, uploads_dir: str, tasks_dir: str, user: str
    ) -> None:
        proc = self._run(
            [
                "sdci-server",
                "setup",
                "--ip",
                ip,
                "--token",
                token,
                "--uploads-dir",
                uploads_dir,
                "--tasks-dir",
                tasks_dir,
                "--user",
                user,
            ],
            timeout=SDCI_SETUP_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"sdci-server setup failed (rc {proc.returncode}): {detail}"
            )
