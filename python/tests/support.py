"""Helpers shared by integration tests and conftest."""

import subprocess
from collections.abc import Sequence
from pathlib import Path


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
