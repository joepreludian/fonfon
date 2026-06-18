"""Fonfon — an opinionated VPS configurator."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return Fonfon's version, sourced from pyproject's project.version.

    The value is read from the installed package metadata, which the build
    backend populates from ``[project].version`` in ``pyproject.toml`` — that
    table is the single source of truth.
    """
    try:
        return version("fonfon")
    except PackageNotFoundError:  # pragma: no cover - only when not installed
        return "0.0.0+unknown"
