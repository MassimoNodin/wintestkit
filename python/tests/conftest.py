"""Shared test fixtures and integration-test collection rules."""

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def demo_app_path() -> Path:
    """Locate the built demo app, skipping tests when it is unavailable."""
    default_path = (
        Path(__file__).resolve().parents[2]
        / "demo"
        / "DemoApp"
        / "bin"
        / "Release"
        / "net8.0-windows"
        / "DemoApp.exe"
    )
    app_path = Path(os.environ.get("WTK_DEMO_APP", str(default_path)))
    if not app_path.is_file():
        pytest.skip("demo app not built: run dotnet build demo/DemoApp -c Release")
    return app_path


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip desktop integration tests on platforms other than Windows."""
    if sys.platform == "win32":
        return
    skip_integration = pytest.mark.skip(reason="integration tests require Windows")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)
