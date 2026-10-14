"""Shared test fixtures and integration-test collection rules."""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from support import DemoProcess, start_demo

pytest_plugins = ["pytester"]


def _default_demo_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "demo"
        / "DemoApp"
        / "bin"
        / "Release"
        / "net8.0-windows"
        / "DemoApp.exe"
    )


@pytest.fixture(scope="session")
def demo_app_path() -> Path:
    """Locate the built demo app, skipping tests when it is unavailable."""
    app_path = Path(os.environ.get("WTK_DEMO_APP", str(_default_demo_path())))
    if not app_path.is_file():
        pytest.skip("demo app not built: run dotnet build demo/DemoApp -c Release")
    return app_path


@pytest.fixture
def demo_process(demo_app_path: Path) -> Iterator[DemoProcess]:
    """Start a fresh demo app and wait for its main window to appear."""
    from wintestkit.uia import com, element, win32
    from wintestkit.uia.constants import TreeScope

    demo = start_demo(demo_app_path)
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            windows = [
                h for h in win32.top_level_windows({demo.pid}) if win32.window_text(h) == "WTK Demo"
            ]
            if windows:
                demo.hwnd = windows[0]
                break
            time.sleep(0.1)
        else:
            pytest.fail("demo app main window did not appear")
        # The title shows up before WPF has published its UIA tree; wait until it is usable.
        status = com.create_condition(automation_id="StatusText")
        while time.monotonic() < deadline:
            window = element.from_handle(demo.hwnd)
            if window.find_first(TreeScope.Descendants, status) is not None:
                break
            time.sleep(0.1)
        else:
            pytest.fail("demo app UI Automation tree did not become ready")
        yield demo
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(demo.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        demo.process.wait(timeout=10)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip desktop integration tests on platforms other than Windows."""
    if sys.platform == "win32":
        return
    skip_integration = pytest.mark.skip(reason="integration tests require Windows")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)
