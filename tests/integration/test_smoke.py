"""Smoke test: the fonfon scie runs inside the VM and reports its version.

This is the seed assertion for the integration harness. As fonfon grows real
provisioning features, service/systemd/SSH assertions will join this file.
"""

import pytest

from fonfon import get_version

PROJECT_VERSION = get_version()


@pytest.mark.integration
def test_fonfon_version_in_vm(vm_run):
    """`fonfon --version` exits 0 and reports the project version in the VM."""
    # sudo is intentional: it exercises the privileged path fonfon uses to
    # provision a server (package installs, systemd, SSH hardening).
    result = vm_run(f"sudo {vm_run.scie} --version")

    assert result.returncode == 0, (
        f"fonfon --version exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert PROJECT_VERSION in result.stdout, (
        f"expected version {PROJECT_VERSION!r} in output, got: {result.stdout!r}"
    )


@pytest.mark.integration
def test_check_runs_on_real_debian(vm_run):
    """`fonfon check --output json` emits valid JSON on a real Debian VM.

    check may exit non-zero on an unprovisioned box (missing packages/services
    are expected); we only assert that it ran and produced JSON output.
    """
    result = vm_run(f"sudo {vm_run.scie} check --output json")
    # check may exit non-zero (unprovisioned box); we assert it ran and emitted JSON
    assert '"sections"' in result.stdout, (
        f"expected JSON with 'sections' key in stdout, got: {result.stdout!r}\n"
        f"stderr: {result.stderr}"
    )
