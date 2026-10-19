"""Lossless report images, screenshot capture defaults and explicit PNG export."""

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from wintestkit import artifacts
from wintestkit.engine import treedump
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import Rect
from wintestkit.uia.png import encode_png
from wintestkit.uia.webp import encode_webp

WIDTH, HEIGHT = 7, 12
PIXELS = bytes(range(WIDTH * HEIGHT * 3))


def assert_image(data: bytes, expected_format: str) -> None:
    with Image.open(BytesIO(data)) as image:
        assert image.format == expected_format
        assert image.size == (WIDTH, HEIGHT)
        assert image.convert("RGB").tobytes() == PIXELS


def test_capture_apis_default_to_lossless_webp(monkeypatch: pytest.MonkeyPatch) -> None:
    bounds = Rect(0, 0, WIDTH, HEIGHT)
    monkeypatch.setattr(win32, "virtual_screen_rect", lambda: bounds)
    monkeypatch.setattr(screenshot, "_capture_pixels", lambda *args: (WIDTH, HEIGHT, PIXELS))
    assert screenshot.capture_screen_pixels() == (WIDTH, HEIGHT, PIXELS)
    element = Mock(rect=bounds)
    for captured in (
        screenshot.capture(bounds),
        screenshot.capture_screen(),
        screenshot.capture_element(element),
    ):
        assert captured is not None
        assert_image(captured, "WEBP")


@pytest.mark.parametrize("source_format", ["png", "webp"])
@pytest.mark.parametrize("extension", [".png", ".webp", ".PNG", ".WEBP"])
def test_save_uses_extension_and_preserves_pixels(
    tmp_path: Path, source_format: str, extension: str
) -> None:
    encoder = encode_png if source_format == "png" else encode_webp
    captured = encoder(WIDTH, HEIGHT, PIXELS)
    path = tmp_path / "export" / f"capture{extension}"
    assert screenshot.save(captured, path) == path
    assert_image(path.read_bytes(), extension[1:].upper())
    if extension[1:].lower() == source_format:
        assert path.read_bytes() == captured


def test_save_rejects_unsupported_extension_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "capture.jpg"
    with pytest.raises(ValueError, match=r"\.webp or \.png"):
        screenshot.save(encode_webp(WIDTH, HEIGHT, PIXELS), path)
    assert not path.exists()


@pytest.mark.parametrize("width,height,pixels", [(0, 1, b""), (1, 1, b""), (1, 1, b"1234")])
def test_webp_rejects_invalid_pixels(width: int, height: int, pixels: bytes) -> None:
    with pytest.raises(ValueError):
        encode_webp(width, height, pixels)


def test_failure_and_step_artifacts_are_webp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = encode_webp(WIDTH, HEIGHT, PIXELS)
    app = Mock()
    app.main_window.return_value.native_window_handle = 42
    monkeypatch.setattr(screenshot, "capture_window", lambda hwnd: captured)
    monkeypatch.setattr(screenshot, "capture_screen", lambda: captured)
    monkeypatch.setattr(treedump, "dump", lambda *args, **kwargs: "Window")
    failure = artifacts.capture_failure(app, tmp_path)
    assert failure.screenshots == [tmp_path / "window.webp", tmp_path / "desktop.webp"]
    assert failure.tree_dump == tmp_path / "tree.txt"
    step = artifacts.capture_step_screenshot(app, tmp_path, 3)
    assert step == tmp_path / "steps/3.webp"
    for path in [*failure.screenshots, step]:
        assert_image(path.read_bytes(), "WEBP")
    assert not list(tmp_path.rglob("*.png"))


def test_failed_window_capture_does_not_prevent_desktop_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(hwnd: int) -> bytes:
        raise OSError("window unavailable")

    monkeypatch.setattr(screenshot, "capture_window", unavailable)
    monkeypatch.setattr(screenshot, "capture_screen", lambda: encode_webp(WIDTH, HEIGHT, PIXELS))
    monkeypatch.setattr(treedump, "dump", lambda *args, **kwargs: "Window")
    assert artifacts.capture_step_screenshot(Mock(), tmp_path, 1) is None
    failure = artifacts.capture_failure(Mock(), tmp_path)
    assert failure.screenshots == [tmp_path / "desktop.webp"]
    assert_image(failure.screenshots[0].read_bytes(), "WEBP")
