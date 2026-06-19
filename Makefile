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
.PHONY: build clean test test-integration debian-login debian-destroy

build: ## Build self-contained linux + macOS (x86_64 and aarch64) executables into dist/
	@mkdir -p $(DIST)
	uv run pex . -c $(NAME) -o $(DIST)/$(NAME) --scie eager \
		--scie-platform linux-x86_64 \
		--scie-platform linux-aarch64 \
		--scie-platform macos-x86_64 \
		--scie-platform macos-aarch64 -v
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

debian-destroy: ## Stop and delete the Debian dev VM
	ARCH=$(ARCH) bash tools/debian-dev.sh destroy
