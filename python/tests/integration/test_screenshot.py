"""Desktop screenshot and rectangle tests without a fixture app."""

import struct

import pytest

from wintestkit.uia import element, screenshot, win32

pytestmark = pytest.mark.integration


def png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    return width, height


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
