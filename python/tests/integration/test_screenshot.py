"""Desktop screenshot and rectangle tests without a fixture app."""

from io import BytesIO

import pytest
from PIL import Image

from wintestkit.uia import element, screenshot, win32

pytestmark = pytest.mark.integration


def webp_size(captured: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(captured)) as image:
        assert image.format == "WEBP"
        return image.size


def test_capture_screen_matches_virtual_screen() -> None:
    screen = win32.virtual_screen_rect()
    assert webp_size(screenshot.capture_screen()) == (screen.width, screen.height)


def test_capture_rejects_empty_rect() -> None:
    with pytest.raises(ValueError, match="empty"):
        screenshot.capture(element.Rect(0, 0, 0, 0))


def test_clip() -> None:
    bounds = element.Rect(0, 0, 100, 100)
    assert screenshot.clip(element.Rect(-10, -10, 30, 30), bounds) == element.Rect(0, 0, 20, 20)
    assert screenshot.clip(element.Rect(200, 0, 10, 10), bounds) is None
