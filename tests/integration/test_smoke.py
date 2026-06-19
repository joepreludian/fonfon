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


@pytest.mark.integration
def test_setup_runs_on_real_debian(vm_run):
    """`fonfon setup --output json` provisions the server and reports steps.

    First run: each step should be installed (or skipped if already present).
    Second run (idempotency): every step must be reported as skipped because
    the system is already fully provisioned.
    """
    result = vm_run(f"sudo {vm_run.scie} setup ituser --output json")
    assert '"steps"' in result.stdout, (
        f"expected JSON with 'steps' key in stdout, got: {result.stdout!r}\n"
        f"stderr: {result.stderr}"
    )

    # Idempotency: a second run must report every step as skipped.
    result2 = vm_run(f"sudo {vm_run.scie} setup ituser --output json")
    assert '"steps"' in result2.stdout, (
        f"expected JSON with 'steps' key on second run, got: {result2.stdout!r}\n"
        f"stderr: {result2.stderr}"
    )
    assert '"skipped"' in result2.stdout, (
        f"expected all steps to be 'skipped' on second run, got: {result2.stdout!r}\n"
        f"stderr: {result2.stderr}"
    )
