#!/usr/bin/env python3
"""Compare pyproject.toml's [project].version against a baseline git ref.

Modes:
  check_version_bump.py <baseline-ref>          strict: print the comparison and
                                                exit 1 if the version was not
                                                raised (used as a PR gate).
  check_version_bump.py --gate <baseline-ref>   print 'true' if the version was
                                                raised, else 'false'; always
                                                exit 0 (used to decide whether a
                                                push to main should publish).
  check_version_bump.py --current               print the working-tree version.

"baseline-ref" is the base branch for a PR, or the previous commit on main.

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


def bumped(base: str, current: str) -> bool:
    return parse(current) > parse(base)


def main(argv: list[str]) -> int:
    args = argv[1:]

    if args == ["--current"]:
        print(current_version())
        return 0

    gate = False
    if args and args[0] == "--gate":
        gate, args = True, args[1:]

    if len(args) != 1:
        print(
            "usage: check_version_bump.py [--gate] <baseline-git-ref> | --current",
            file=sys.stderr,
        )
        return 2

    baseline = args[0]
    base = version_at_ref(baseline)
    current = current_version()

    if gate:
        print("true" if bumped(base, current) else "false")
        return 0

    print(f"baseline ({baseline}) version: {base}")
    print(f"current version:             {current}")
    if current == base:
        print(
            f"::error::pyproject.toml version was not bumped (still {current}). "
            "Bump [project].version per the project convention.",
            file=sys.stderr,
        )
        return 1
    if not bumped(base, current):
        print(
            f"::error::pyproject.toml version went backwards: {base} -> {current}.",
            file=sys.stderr,
        )
        return 1

    print(f"Version bumped: {base} -> {current}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
