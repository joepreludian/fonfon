#!/usr/bin/env python3
"""Fail if pyproject.toml's [project].version was not bumped vs a baseline ref.

Usage: check_version_bump.py <baseline-git-ref>

Compares the working-tree ``pyproject.toml`` version against the version at the
given git ref — the base branch for a PR, or the previous commit on ``main``.
Exits non-zero (failing CI) when the version is unchanged or went backwards,
enforcing the project's "bump the version on every change" rule.

Parses the version with a tiny regex rather than ``tomllib`` so it runs on any
Python 3 (the helper is invoked by CI and locally, where stdlib TOML may be
missing on older interpreters).
"""

import re
import subprocess
import sys

_VERSION_RE = re.compile(r"""^version\s*=\s*["']([^"']+)["']""")


def _version(text: str) -> str:
    """Extract [project].version from pyproject.toml text."""
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if in_project:
            match = _VERSION_RE.match(stripped)
            if match:
                return match.group(1)
    raise SystemExit("could not find [project].version in pyproject.toml")


def version_at_ref(ref: str) -> str:
    out = subprocess.run(
        ["git", "show", f"{ref}:pyproject.toml"],
        capture_output=True,
        check=True,
    )
    return _version(out.stdout.decode())


def current_version() -> str:
    with open("pyproject.toml", encoding="utf-8") as fh:
        return _version(fh.read())


def parse(version: str) -> tuple:
    """Best-effort orderable key: numeric parts sort before alpha (pre-release)."""
    parts = []
    for chunk in version.replace("-", ".").split("."):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, 0, chunk))
    return tuple(parts)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_version_bump.py <baseline-git-ref>", file=sys.stderr)
        return 2

    baseline = sys.argv[1]
    base = version_at_ref(baseline)
    current = current_version()
    print(f"baseline ({baseline}) version: {base}")
    print(f"current version:             {current}")

    if current == base:
        print(
            f"::error::pyproject.toml version was not bumped (still {current}). "
            "Bump [project].version per the project convention.",
            file=sys.stderr,
        )
        return 1
    if parse(current) < parse(base):
        print(
            f"::error::pyproject.toml version went backwards: {base} -> {current}.",
            file=sys.stderr,
        )
        return 1

    print(f"Version bumped: {base} -> {current}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
