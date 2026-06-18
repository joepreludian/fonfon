"""The displayed version must come from pyproject's project.version."""

import tomllib
from pathlib import Path

from fonfon import get_version


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    return data["project"]["version"]


def test_get_version_matches_pyproject():
    assert get_version() == _pyproject_version()
