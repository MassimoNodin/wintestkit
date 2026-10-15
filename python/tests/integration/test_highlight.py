"""Spy highlighting raises covered application windows and restores minimized windows."""

import io
import subprocess
import time
from pathlib import Path

import pytest
from support import DemoProcess, start_demo

from wintestkit.app import App
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.server import Server
from wintestkit.uia import patterns, win32

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("target", ["window", "child", "minimized_child"])
def test_highlight_raises_covered_app(
    demo_process: DemoProcess, demo_app_path: Path, tmp_path: Path, target: str
) -> None:
    app = App.attach(pid=demo_process.pid)
    window = app.main_window()
    status = resolve(Scope(app), Locator(automation_id="StatusText"))
    node = window if target == "window" else status
    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\n", encoding="utf-8")
    server = Server(io.BytesIO())
    server.dispatch("initialize", {"root": str(tmp_path)})
    registered = server._register(node)
    covering_app = start_demo(demo_app_path)
    try:
        deadline = time.monotonic() + 15
        covering_windows: list[int] = []
        while time.monotonic() < deadline:
            covering_windows = [
                handle
                for handle in win32.top_level_windows({covering_app.pid})
                if win32.window_text(handle) == "WTK Demo"
            ]
            if covering_windows:
                break
            time.sleep(0.05)
        assert covering_windows, "covering application did not create its window"
        if target == "minimized_child":
            patterns.window_set_state(window, "minimized")
            assert win32.IsIconic(demo_process.hwnd)
        assert win32.bring_to_foreground(covering_windows[0])
        assert win32.GetForegroundWindow() != demo_process.hwnd
        server.dispatch("inspect.highlight", {"nodeId": registered["nodeId"], "durationMs": 200})
        assert win32.GetForegroundWindow() == demo_process.hwnd
        assert not win32.IsIconic(demo_process.hwnd)
        assert status.name == "Ready"
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(covering_app.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        covering_app.process.wait(timeout=10)
