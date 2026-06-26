#!/usr/bin/env bash
#
# Interactive Debian dev VM for trying the fonfon scie by hand.
#
# `login` builds the scie on this (source) machine, boots or reuses a Debian 12
# Lima VM, injects the freshly built binary onto the guest's PATH as `fonfon`,
# and drops you into a shell. Exiting the shell leaves the VM running so you can
# log back in; `destroy` stops and deletes it.
#
# `deploy` rebuilds the scie and copies it onto the already-running VM (no
# recreate, no shell) -- the quick "I changed the code, push it to the VM" loop.
#
# `demo` runs a full end-to-end on a FRESH VM: build, recreate, install, then
# `fonfon check` followed by `fonfon setup preludian`. Set TAILSCALE_AUTH_KEY in
# the environment to also join the tailnet and configure sdci; without it the
# setup stops at the required-key gate.
#
# Usage:
#   tools/debian-dev.sh login              # aarch64 (default)
#   ARCH=x86_64 tools/debian-dev.sh login  # emulated x86_64
#   tools/debian-dev.sh deploy             # rebuild + copy onto the running VM
#   tools/debian-dev.sh destroy
#   tools/debian-dev.sh demo
#
# Normally invoked via `make debian-login` / `make debian-deploy` /
# `make debian-destroy` / `make debian-demo`.
set -euo pipefail

ARCH="${ARCH:-aarch64}"
VM_NAME="${VM_NAME:-fonfon-dev}"        # distinct from the integration VM (fonfon-test)
SCIE_IN_VM="/usr/local/bin/fonfon"      # on PATH so you can just type `fonfon`
STAGE_IN_VM="/tmp/fonfon"               # scratch landing spot before install
DEMO_USER="preludian"                   # operator user created by `make debian-demo`

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
    # Pair the scie interpreter with the matching wheel target so pydantic-core's
    # native cp314 wheel for this arch is bundled (see Makefile for the why).
    uv run pex . -c fonfon -o dist/fonfon --scie eager \
      --scie-name-style platform-file-suffix --scie-platform "linux-${ARCH}" \
      --platform "manylinux_2_17_${ARCH}-cp-314-cp314"
    rm -f dist/fonfon
  )
  if [[ ! -x "${SCIE_HOST}" ]]; then
    echo "error: expected scie not found at ${SCIE_HOST}" >&2
    exit 1
  fi
}

# Copy the freshly built scie into the running VM and install it onto PATH.
inject_scie() {
  echo ">> Injecting fresh scie -> ${VM_NAME}:${SCIE_IN_VM} ..."
  limactl copy "${SCIE_HOST}" "${VM_NAME}:${STAGE_IN_VM}"
  limactl shell "${VM_NAME}" -- sudo install -m 0755 "${STAGE_IN_VM}" "${SCIE_IN_VM}"
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

  inject_scie

  cat <<EOF
>> Ready. Entering '${VM_NAME}'. 'fonfon' is on PATH, e.g.:
>>     fonfon check
>> Exit with 'exit' or Ctrl-D; the VM keeps running.
>> Tear it down with:  make debian-destroy
EOF
  limactl shell "${VM_NAME}"
}

# Rebuild the scie and copy it onto the already-running VM. Assumes the VM
# exists and is running (e.g. after `make debian-login`); errors fast otherwise.
cmd_deploy() {
  require_lima
  check_arch

  local status
  status="$(vm_status)"
  if [[ "${status}" != "Running" ]]; then
    echo "error: VM '${VM_NAME}' is not running (status: ${status:-absent})." >&2
    echo "Start it first with:  make debian-login" >&2
    exit 1
  fi

  build_scie
  inject_scie

  echo ">> Deployed fresh fonfon to '${VM_NAME}:${SCIE_IN_VM}'. Check it with:"
  echo ">>     limactl shell ${VM_NAME} -- fonfon --version"
}

cmd_destroy() {
  require_lima
  echo ">> Stopping and deleting VM '${VM_NAME}' ..."
  # `delete -f` removes the instance even while running, so it is a single,
  # idempotent teardown that never errors if the VM is already gone.
  limactl delete -f "${VM_NAME}" >/dev/null 2>&1 || true
  echo ">> Done."
}

# Full end-to-end on a FRESH VM: build, recreate the VM, install fonfon, then
# run `fonfon check` (a fresh box is expected to report gaps) followed by
# `fonfon setup ${DEMO_USER}`. The VM is left running afterwards for inspection.
cmd_demo() {
  require_lima
  check_arch
  build_scie

  echo ">> Destroying any existing VM '${VM_NAME}' ..."
  limactl delete -f "${VM_NAME}" >/dev/null 2>&1 || true

  echo ">> Creating a fresh Debian VM '${VM_NAME}' (arch=${ARCH}) ..."
  limactl start --name "${VM_NAME}" --arch "${ARCH}" --tty=false "${TEMPLATE}"

  inject_scie

  echo ">> Running 'fonfon check' (a fresh box is expected to report gaps) ..."
  limactl shell "${VM_NAME}" -- sudo "${SCIE_IN_VM}" check || true

  echo ">> Running 'fonfon setup ${DEMO_USER}' ..."
  if [[ -n "${TAILSCALE_AUTH_KEY:-}" ]]; then
    limactl shell "${VM_NAME}" -- sudo "${SCIE_IN_VM}" \
      setup "${DEMO_USER}" --tailscale-key "${TAILSCALE_AUTH_KEY}"
  else
    echo ">> No TAILSCALE_AUTH_KEY in env -- setup will stop at the required-key gate (demo)."
    limactl shell "${VM_NAME}" -- sudo "${SCIE_IN_VM}" setup "${DEMO_USER}" || true
  fi

  echo ">> Done. VM '${VM_NAME}' left running -- 'make debian-login' to enter, 'make debian-destroy' to remove."
}

case "${1:-}" in
  login) cmd_login ;;
  deploy) cmd_deploy ;;
  destroy) cmd_destroy ;;
  demo) cmd_demo ;;
  *)
    echo "usage: $0 {login|deploy|destroy|demo}" >&2
    exit 2
    ;;
esac
