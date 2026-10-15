"""Highlight placement stays inside the requested screen bounds."""

import queue
import threading

import pytest

from wintestkit.engine import overlay
from wintestkit.uia import win32
from wintestkit.uia.element import Rect


@pytest.mark.parametrize(
    "rect",
    [Rect(100, 80, 640, 480), Rect(-800, -200, 640, 480), Rect(10, 20, 1, 2)],
)
@pytest.mark.parametrize("thickness", [1, 3, 8])
def test_highlight_does_not_expand_target_bounds(
    monkeypatch: pytest.MonkeyPatch, rect: Rect, thickness: int
) -> None:
    shown = object.__new__(overlay.Overlay)
    shown._thickness = thickness
    shown._requests = queue.Queue()
    done = threading.Event()
    shown._requests.put((overlay._WM_SHOW, rect, done))
    positions: list[tuple[int, ...]] = []
    invalidations: list[int] = []
    monkeypatch.setattr(win32, "SetWindowPos", lambda *args: positions.append(args))
    monkeypatch.setattr(
        win32, "InvalidateRect", lambda hwnd, region, erase: invalidations.append(hwnd)
    )

    shown._handle(123, overlay._WM_SHOW)

    assert positions == [
        (
            123,
            win32.HWND_TOPMOST,
            rect.left,
            rect.top,
            rect.width,
            rect.height,
            win32.SWP_NOACTIVATE | win32.SWP_SHOWWINDOW,
        )
    ]
    assert invalidations == [123]
    assert done.is_set()
