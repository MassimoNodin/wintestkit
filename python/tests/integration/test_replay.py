"""Native isolated-window capture with a controlled, non-sensitive test window."""

import struct
import time
import zlib
from pathlib import Path

import pytest

from wintestkit.replay import ReplayRecorder
from wintestkit.uia import screenshot, win32

pytestmark = pytest.mark.integration


def test_window_capture_excludes_overlapping_window(tmp_path: Path) -> None:
    tkinter = pytest.importorskip("tkinter")
    root = tkinter.Tk()
    cover = None
    try:
        root.title("WinTestKit replay capture verification")
        root.geometry("320x200+80+80")
        root.configure(background="#ff0000")
        root.update()
        hwnd = win32.root_window(root.winfo_id())
        cover = tkinter.Toplevel(root)
        cover.geometry("340x240+70+70")
        cover.configure(background="#0000ff")
        cover.update()
        cover.lift()
        root.update()
        png = screenshot.capture_window(hwnd, win32.window_pid(hwnd))
        assert png is not None
        width, height = struct.unpack(">II", png[16:24])
        position = 8
        compressed = b""
        while position < len(png):
            length = struct.unpack(">I", png[position : position + 4])[0]
            if png[position + 4 : position + 8] == b"IDAT":
                compressed += png[position + 8 : position + 8 + length]
            position += 12 + length
        raw = zlib.decompress(compressed)
        offset = (height // 2) * (width * 3 + 1) + 1 + (width // 2) * 3
        assert raw[offset : offset + 3] == bytes((255, 0, 0))
        replay = ReplayRecorder(tmp_path, tmp_path, fps=10)
        replay.set_window(hwnd)
        replay.start()
        try:
            deadline = time.monotonic() + 3
            while not replay.frames and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
        finally:
            result = replay.stop()
        assert result["frames"], result
        assert (tmp_path / result["frames"][0]["path"]).is_file()
    finally:
        if cover is not None:
            cover.destroy()
        root.destroy()
