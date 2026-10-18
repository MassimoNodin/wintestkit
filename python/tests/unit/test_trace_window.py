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
    calls: list[tuple[Rect, int | None]] = []

    def bitmap(rect: Rect, hwnd: int | None = None) -> bytes:
        calls.append((rect, hwnd))
        return b"window-content"

    monkeypatch.setattr(screenshot, "_capture_bitmap", bitmap)
    assert screenshot.capture_window(42) == b"window-content"
    assert calls == [(Rect(10, 20, 100, 80), 42)]


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
