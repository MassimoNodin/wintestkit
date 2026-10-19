"""Native isolated-window capture with a controlled, non-sensitive test window."""

import time
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

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
        captured = screenshot.capture_window(hwnd, win32.window_pid(hwnd))
        assert captured is not None
        with Image.open(BytesIO(captured)) as image:
            assert image.format == "WEBP"
            assert image.convert("RGB").getpixel((image.width // 2, image.height // 2)) == (
                255,
                0,
                0,
            )
            expected_pixels = image.convert("RGB").tobytes()
        exported = screenshot.save(captured, tmp_path / "export.png")
        with Image.open(exported) as image:
            assert image.format == "PNG"
            assert image.convert("RGB").tobytes() == expected_pixels
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
        recorded = tmp_path / result["frames"][0]["path"]
        assert recorded.suffix == ".webp"
        with Image.open(recorded) as image:
            assert image.format == "WEBP"
            assert image.convert("RGB").getpixel((image.width // 2, image.height // 2)) == (
                255,
                0,
                0,
            )
    finally:
        if cover is not None:
            cover.destroy()
        root.destroy()
