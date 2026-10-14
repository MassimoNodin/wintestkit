"""Integration tests for screenshots and DPI awareness."""

import struct
from pathlib import Path

import pytest
from support import DemoProcess

from wintestkit.uia import dpi, element, screenshot, win32

pytestmark = pytest.mark.integration


def png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    return width, height


def test_capture_main_window(demo_process: DemoProcess, tmp_path: Path) -> None:
    assert win32.bring_to_foreground(demo_process.hwnd)
    window = element.from_handle(demo_process.hwnd)
    rect = window.rect
    assert rect is not None
    png = screenshot.capture_element(window)
    assert png is not None
    width, height = png_size(png)
    visible = screenshot.clip(rect, win32.virtual_screen_rect())
    assert visible is not None
    assert abs(width - visible.width) <= 2
    assert abs(height - visible.height) <= 2
    saved = screenshot.save(png, tmp_path / "nested" / "window.png")
    assert saved.read_bytes() == png


def test_capture_screen_matches_virtual_screen() -> None:
    screen = win32.virtual_screen_rect()
    assert png_size(screenshot.capture_screen()) == (screen.width, screen.height)


def test_capture_rejects_empty_rect() -> None:
    with pytest.raises(ValueError, match="empty"):
        screenshot.capture(element.Rect(0, 0, 0, 0))


def test_clip() -> None:
    bounds = element.Rect(0, 0, 100, 100)
    assert screenshot.clip(element.Rect(-10, -10, 30, 30), bounds) == element.Rect(0, 0, 20, 20)
    assert screenshot.clip(element.Rect(200, 0, 10, 10), bounds) is None


def test_process_is_per_monitor_aware(demo_process: DemoProcess) -> None:
    dpi.ensure_per_monitor_aware()  # idempotent
    assert dpi.scale_for_window(demo_process.hwnd) >= 1.0
    assert win32.GetDpiForSystem() >= 96
