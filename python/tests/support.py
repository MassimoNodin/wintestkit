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


def decode_png_rgb(png: bytes) -> tuple[int, int, bytes]:
    """Decode PNGs produced by wintestkit.uia.png (8-bit RGB, filter 0) to raw RGB bytes."""
    import struct
    import zlib

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    position, idat, width, height = 8, b"", 0, 0
    while position < len(png):
        (length,) = struct.unpack(">I", png[position : position + 4])
        kind = png[position + 4 : position + 8]
        data = png[position + 8 : position + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", data[:8])
        elif kind == b"IDAT":
            idat += data
        position += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(height))
    return width, height, rows
