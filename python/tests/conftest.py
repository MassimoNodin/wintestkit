"""Shared test fixtures and integration-test collection rules."""

import sys

import pytest

pytest_plugins = ["pytester"]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip desktop integration tests on platforms other than Windows."""
    if sys.platform == "win32":
        return
    skip_integration = pytest.mark.skip(reason="integration tests require Windows")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)
