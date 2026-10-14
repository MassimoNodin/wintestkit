"""Helpers shared by integration tests and conftest."""

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any


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


def window_props(app: Any, attribute: str) -> list[str]:
    """Property of every top-level window, skipping windows that close mid-enumeration."""
    from wintestkit.errors import UIAError

    values: list[str] = []
    for window in app.top_level_windows():
        try:
            values.append(getattr(window, attribute))
        except UIAError:
            continue
    return values
