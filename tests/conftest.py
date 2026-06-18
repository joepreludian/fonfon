"""Top-level pytest wiring shared by the whole test tree.

The ``--run-integration`` option lives here (rather than in
``tests/integration/conftest.py``) so it is registered for every invocation --
including ``uv run pytest`` from the repo root -- and never trips the
"unrecognized arguments" error. The integration tests are opt-in: by default
they are skipped so the fast unit suite never triggers a VM boot.
"""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests that boot a real VM (default: skip them)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="integration test (use --run-integration or run.sh)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
