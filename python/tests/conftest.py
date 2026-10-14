"""Shared test fixtures and integration-test collection rules."""

import os
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest


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


class DemoProcess:
    """A demo app subprocess started by a test, without using wintestkit.app."""

    def __init__(self, process: "subprocess.Popen[bytes]") -> None:
        self.process = process
        self.hwnd = 0

    @property
    def pid(self) -> int:
        return self.process.pid


def start_demo(path: Path, args: Sequence[str] = ()) -> DemoProcess:
    return DemoProcess(subprocess.Popen([str(path), *args]))


@pytest.fixture
def demo_process(demo_app_path: Path) -> Iterator[DemoProcess]:
    """Start a fresh demo app and wait for its main window to appear."""
    from wintestkit.uia import win32

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
