# Fonfon build automation.
#
# `make build` produces standalone, self-contained executables (PEX scies)
# with an embedded Python interpreter -- one per target architecture -- in
# dist/. They run on a Linux or macOS host with no Python or dependencies
# installed.

DIST := dist
NAME := fonfon

.DEFAULT_GOAL := build
.PHONY: build clean

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
