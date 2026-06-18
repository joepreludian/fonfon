#!/usr/bin/env bash
#
# Integration-test lifecycle for fonfon.
#
# Builds the fonfon scie for the target architecture, boots a fresh Debian 12
# VM with Lima, injects the scie, runs the pytest integration suite against the
# running VM, then tears the VM down -- even on failure (trap on EXIT).
#
# Usage:
#   tests/integration/run.sh              # aarch64 (default)
#   ARCH=x86_64 tests/integration/run.sh  # emulated x86_64
#
# Normally invoked via `make test-integration [ARCH=...]`.
set -euo pipefail

ARCH="${ARCH:-aarch64}"
VM_NAME="${VM_NAME:-fonfon-test}"
SCIE_IN_VM="/tmp/fonfon"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${SCRIPT_DIR}/lima-debian.yaml"

case "${ARCH}" in
  aarch64 | x86_64) ;;
  *)
    echo "error: unsupported ARCH '${ARCH}'. Use 'aarch64' or 'x86_64'." >&2
    exit 2
    ;;
esac

if ! command -v limactl >/dev/null 2>&1; then
  cat >&2 <<'EOF'
error: limactl (Lima) is not installed.

The integration harness boots a real Debian VM with Lima. Install it with:

    brew install lima

Then re-run:

    make test-integration
EOF
  exit 1
fi

SCIE_HOST="${REPO_ROOT}/dist/fonfon-linux-${ARCH}"

cleanup() {
  # Tear the VM down on any exit so no VM is ever left behind.
  # `delete -f` removes the instance even while it is running, so it is a
  # single, idempotent source of truth for teardown.
  limactl delete -f "${VM_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo ">> Building fonfon scie for linux-${ARCH} ..."
(
  cd "${REPO_ROOT}"
  uv run pex . -c fonfon -o dist/fonfon --scie eager \
    --scie-name-style platform-file-suffix --scie-platform "linux-${ARCH}"
  rm -f dist/fonfon
)

if [[ ! -x "${SCIE_HOST}" ]]; then
  echo "error: expected scie not found at ${SCIE_HOST}" >&2
  exit 1
fi

echo ">> Removing any stale VM named '${VM_NAME}' ..."
cleanup

echo ">> Starting fresh Debian VM '${VM_NAME}' (arch=${ARCH}) ..."
limactl start --name "${VM_NAME}" --arch "${ARCH}" --tty=false "${TEMPLATE}"

echo ">> Injecting scie into ${VM_NAME}:${SCIE_IN_VM} ..."
limactl copy "${SCIE_HOST}" "${VM_NAME}:${SCIE_IN_VM}"
limactl shell "${VM_NAME}" -- chmod +x "${SCIE_IN_VM}"

echo ">> Running integration assertions ..."
cd "${REPO_ROOT}"
FONFON_TEST_VM="${VM_NAME}" FONFON_TEST_SCIE="${SCIE_IN_VM}" \
  uv run pytest tests/integration --run-integration -v

echo ">> Integration suite finished successfully."
