#!/usr/bin/env bash
#
# Interactive Debian dev VM for trying the fonfon scie by hand.
#
# `login` builds the scie on this (source) machine, boots or reuses a Debian 12
# Lima VM, injects the freshly built binary onto the guest's PATH as `fonfon`,
# and drops you into a shell. Exiting the shell leaves the VM running so you can
# log back in; `destroy` stops and deletes it.
#
# Usage:
#   tools/debian-dev.sh login              # aarch64 (default)
#   ARCH=x86_64 tools/debian-dev.sh login  # emulated x86_64
#   tools/debian-dev.sh destroy
#
# Normally invoked via `make debian-login` / `make debian-destroy`.
set -euo pipefail

ARCH="${ARCH:-aarch64}"
VM_NAME="${VM_NAME:-fonfon-dev}"        # distinct from the integration VM (fonfon-test)
SCIE_IN_VM="/usr/local/bin/fonfon"      # on PATH so you can just type `fonfon`
STAGE_IN_VM="/tmp/fonfon"               # scratch landing spot before install

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${REPO_ROOT}/tests/integration/lima-debian.yaml"
SCIE_HOST="${REPO_ROOT}/dist/fonfon-linux-${ARCH}"

require_lima() {
  if ! command -v limactl >/dev/null 2>&1; then
    cat >&2 <<'EOF'
error: limactl (Lima) is not installed.

This opens a real Debian VM with Lima. Install it with:

    brew install lima
EOF
    exit 1
  fi
}

check_arch() {
  case "${ARCH}" in
    aarch64 | x86_64) ;;
    *)
      echo "error: unsupported ARCH '${ARCH}'. Use 'aarch64' or 'x86_64'." >&2
      exit 2
      ;;
  esac
}

# Status of the dev VM: "Running", "Stopped", or empty when it does not exist.
vm_status() {
  limactl list --format '{{.Status}}' "${VM_NAME}" 2>/dev/null || true
}

build_scie() {
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
}

cmd_login() {
  require_lima
  check_arch
  build_scie

  local status
  status="$(vm_status)"
  if [[ -z "${status}" ]]; then
    echo ">> Starting fresh Debian VM '${VM_NAME}' (arch=${ARCH}) ..."
    limactl start --name "${VM_NAME}" --arch "${ARCH}" --tty=false "${TEMPLATE}"
  elif [[ "${status}" != "Running" ]]; then
    echo ">> Starting existing VM '${VM_NAME}' ..."
    limactl start "${VM_NAME}"
  else
    echo ">> Reusing running VM '${VM_NAME}'."
  fi

  echo ">> Injecting fresh scie -> ${VM_NAME}:${SCIE_IN_VM} ..."
  limactl copy "${SCIE_HOST}" "${VM_NAME}:${STAGE_IN_VM}"
  limactl shell "${VM_NAME}" -- sudo install -m 0755 "${STAGE_IN_VM}" "${SCIE_IN_VM}"

  cat <<EOF
>> Ready. Entering '${VM_NAME}'. 'fonfon' is on PATH, e.g.:
>>     fonfon check
>> Exit with 'exit' or Ctrl-D; the VM keeps running.
>> Tear it down with:  make debian-destroy
EOF
  limactl shell "${VM_NAME}"
}

cmd_destroy() {
  require_lima
  echo ">> Stopping and deleting VM '${VM_NAME}' ..."
  # `delete -f` removes the instance even while running, so it is a single,
  # idempotent teardown that never errors if the VM is already gone.
  limactl delete -f "${VM_NAME}" >/dev/null 2>&1 || true
  echo ">> Done."
}

case "${1:-}" in
  login) cmd_login ;;
  destroy) cmd_destroy ;;
  *)
    echo "usage: $0 {login|destroy}" >&2
    exit 2
    ;;
esac
