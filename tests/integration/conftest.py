"""Pytest wiring for the fonfon VM integration suite.

The integration tests boot a real Debian VM via Lima and run the built fonfon
scie inside it. They are opt-in: the default ``uv run pytest`` deselects them so
the fast unit suite never triggers a VM boot. Enable them with
``--run-integration`` (this is what ``tests/integration/run.sh`` does); that
option is registered in the top-level ``tests/conftest.py``.

Even when enabled, the suite skips *gracefully* -- rather than failing -- when
there is no VM to talk to (``limactl`` missing, or ``FONFON_TEST_VM`` unset),
so ``uv run pytest tests/integration --run-integration`` is green on a laptop
without Lima.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass

import pytest

# Populated by run.sh; the vm_run fixture skips when these are absent.
VM_NAME_ENV = "FONFON_TEST_VM"
SCIE_PATH_ENV = "FONFON_TEST_SCIE"
DEFAULT_SCIE_PATH = "/tmp/fonfon"

# Cap each in-VM command so a hung VM can never block pytest/CI forever.
VM_COMMAND_TIMEOUT = 120


@dataclass(frozen=True)
class VMShell:
    """A callable that runs a shell command inside the Lima VM."""

    name: str
    scie: str

    def __call__(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["limactl", "shell", self.name, "--", "bash", "-lc", command],
            capture_output=True,
            text=True,
            check=False,
            timeout=VM_COMMAND_TIMEOUT,
        )


@pytest.fixture
def vm_run() -> VMShell:
    """Return a ``VMShell`` for the running VM, or skip if there is none.

    Usage in a test::

        result = vm_run(f"sudo {vm_run.scie} --version")
    """
    if shutil.which("limactl") is None:
        pytest.skip("limactl not installed; no VM to run integration tests against")

    vm_name = os.environ.get(VM_NAME_ENV)
    if not vm_name:
        pytest.skip(
            f"{VM_NAME_ENV} not set; integration VM not provisioned "
            "(run tests/integration/run.sh)"
        )

    scie = os.environ.get(SCIE_PATH_ENV, DEFAULT_SCIE_PATH)
    return VMShell(name=vm_name, scie=scie)
