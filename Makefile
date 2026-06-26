# Fonfon build automation.
#
# `make build` produces standalone, self-contained executables (PEX scies)
# with an embedded Python interpreter -- one per target architecture -- in
# dist/. They run on a Linux or macOS host with no Python or dependencies
# installed.

DIST := dist
NAME := fonfon

# Architecture for the integration VM: aarch64 (default) or x86_64.
ARCH ?= aarch64

.DEFAULT_GOAL := build
.PHONY: build clean test test-integration debian-login debian-deploy debian-destroy debian-demo

# pydantic-core ships per-platform wheels, so each --scie-platform (which picks the
# embedded interpreter) is paired with a --platform (which picks the wheel target) so
# the resolve bundles the matching cp314 wheel. Bump the cp-314 tag on a Python upgrade.
build: ## Build self-contained linux + macOS (x86_64 and aarch64) executables into dist/
	@mkdir -p $(DIST)
	uv run pex . -c $(NAME) -o $(DIST)/$(NAME) --scie eager \
		--scie-platform linux-x86_64 --platform manylinux_2_17_x86_64-cp-314-cp314 \
		--scie-platform linux-aarch64 --platform manylinux_2_17_aarch64-cp-314-cp314 \
		--scie-platform macos-x86_64 --platform macosx_10_12_x86_64-cp-314-cp314 \
		--scie-platform macos-aarch64 --platform macosx_11_0_arm64-cp-314-cp314 -v
	@rm -f $(DIST)/$(NAME)
	@echo "Built $(NAME) executables in $(DIST)/: linux-x86_64 linux-aarch64 macos-x86_64 macos-aarch64"

clean: ## Remove the dist/ directory
	rm -rf $(DIST)

test: ## Run the fast unit test suite (no VM)
	uv run pytest

test-integration: ## Boot a Debian VM and run the integration suite (ARCH=aarch64|x86_64)
	ARCH=$(ARCH) bash tests/integration/run.sh

debian-login: ## Build the scie, boot/reuse a Debian VM with fonfon on PATH, and open a shell (ARCH=aarch64|x86_64)
	ARCH=$(ARCH) bash tools/debian-dev.sh login

debian-deploy: ## Rebuild the scie and copy it onto the already-running dev VM (ARCH=aarch64|x86_64)
	ARCH=$(ARCH) bash tools/debian-dev.sh deploy

debian-destroy: ## Stop and delete the Debian dev VM
	ARCH=$(ARCH) bash tools/debian-dev.sh destroy

debian-demo: ## Fresh-VM end-to-end: build, recreate VM, install fonfon, run check then setup preludian (ARCH=...)
	ARCH=$(ARCH) bash tools/debian-dev.sh demo
