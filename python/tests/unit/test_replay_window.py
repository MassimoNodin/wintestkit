"""Window recordings never fall back to desktop capture."""

from typing import Any
from unittest.mock import Mock

import pytest

from wintestkit.errors import EnvironmentNotReadyError
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import Rect


def test_window_capture_uses_window_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32, "IsIconic", lambda hwnd: False)

    def bounds(hwnd: int, pointer: Any) -> int:
        pointer._obj.left, pointer._obj.top = 10, 20
        pointer._obj.right, pointer._obj.bottom = 110, 100
        return 1

    monkeypatch.setattr(win32.user32, "GetWindowRect", bounds)

    def frame(hwnd: int, attribute: int, pointer: Any, size: int) -> int:
        # The visible frame sits inside the invisible resize borders.
        visible = pointer._obj
        visible.left, visible.top, visible.right, visible.bottom = 17, 20, 103, 93
        return 0

    dwm = Mock()
    dwm.DwmGetWindowAttribute = frame
    monkeypatch.setattr(win32, "dwmapi", dwm)
    calls: list[tuple[Rect, int | None, Rect | None]] = []

    def pixels(rect: Rect, hwnd: int | None = None, crop: Rect | None = None):
        calls.append((rect, hwnd, crop))
        return 1, 1, b"\x00\x00\x00"

    monkeypatch.setattr(screenshot, "_capture_pixels", pixels)
    assert screenshot.capture_window(42) == screenshot.encode_png(1, 1, b"\x00\x00\x00")
    assert calls == [(Rect(10, 20, 100, 80), 42, Rect(7, 0, 86, 73))]


def test_black_border_hairline_is_trimmed_but_content_is_kept() -> None:
    black, grey = b"\x00\x00\x00", b"\x20\x20\x20"
    # Black on the left, right and bottom edges, as a rendered window leaves them.
    rows = [black + grey * 3 + black] * 3 + [black * 5]
    width, height, rgb = screenshot.trim_black_edges(5, 4, b"".join(rows))
    assert (width, height, rgb) == (3, 3, grey * 9)
    plain = grey * 20
    assert screenshot.trim_black_edges(5, 4, plain) == (5, 4, plain)


def test_window_capture_keeps_whole_window_without_dwm_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dwm = Mock()
    dwm.DwmGetWindowAttribute = lambda *args: 1
    monkeypatch.setattr(win32, "dwmapi", dwm)
    assert screenshot._visible_frame(42, Rect(10, 20, 100, 80)) is None


def test_reused_window_handle_does_not_capture_another_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 200)
    assert screenshot.capture_window(42, expected_pid=100) is None


@pytest.mark.parametrize("minimized", [False, True])
def test_hidden_or_minimized_window_returns_no_frame(
    monkeypatch: pytest.MonkeyPatch, minimized: bool
) -> None:
    monkeypatch.setattr(win32, "IsWindowVisible", lambda hwnd: minimized)
    monkeypatch.setattr(win32, "IsIconic", lambda hwnd: minimized)
    assert screenshot.capture_window(42) is None


@pytest.mark.parametrize("failure", ["dc", "bitmap", "select", "blit", "clear", "print", "read"])
def test_capture_failure_releases_gdi_resources(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(win32, "GetDC", Mock(return_value=10))
    monkeypatch.setattr(
        win32, "CreateCompatibleDC", Mock(return_value=0 if failure == "dc" else 20)
    )
    monkeypatch.setattr(
        win32, "CreateCompatibleBitmap", Mock(return_value=0 if failure == "bitmap" else 30)
    )

    def select(device: Any, bitmap: Any) -> int:
        calls.append(("select", bitmap))
        return 0 if failure == "select" else 40

    monkeypatch.setattr(win32, "SelectObject", select)
    monkeypatch.setattr(win32, "BitBlt", Mock(return_value=0 if failure == "blit" else 1))
    monkeypatch.setattr(win32.gdi32, "PatBlt", Mock(return_value=0 if failure == "clear" else 1))
    monkeypatch.setattr(
        win32.user32, "PrintWindow", Mock(return_value=0 if failure == "print" else 1)
    )
    monkeypatch.setattr(win32, "GetDIBits", Mock(return_value=0))
    monkeypatch.setattr(win32, "DeleteObject", lambda bitmap: calls.append(("delete", bitmap)))
    monkeypatch.setattr(win32, "DeleteDC", lambda device: calls.append(("delete_dc", device)))
    monkeypatch.setattr(win32, "ReleaseDC", lambda hwnd, device: calls.append(("release", device)))

    with pytest.raises(EnvironmentNotReadyError):
        screenshot._capture_bitmap(Rect(0, 0, 2, 2), 42 if failure in {"clear", "print"} else None)

    if failure == "dc":
        assert calls == [("release", 10)]
    elif failure == "bitmap":
        assert calls == [("delete_dc", 20), ("release", 10)]
    elif failure == "select":
        assert calls == [("select", 30), ("delete", 30), ("delete_dc", 20), ("release", 10)]
    else:
        assert calls == [
            ("select", 30),
            ("select", 40),
            ("delete", 30),
            ("delete_dc", 20),
            ("release", 10),
        ]
