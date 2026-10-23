"""Resolve child controls to their owning window, then highlight the restored bounds."""

from typing import Any

import pytest
from fakes import FakeElement

from wintestkit.engine import actions, overlay
from wintestkit.errors import ActionError
from wintestkit.model import _BoundBase
from wintestkit.uia import win32
from wintestkit.uia.element import Rect


@pytest.mark.parametrize("child_handle", [0, 101])
def test_child_raises_owning_window(monkeypatch: pytest.MonkeyPatch, child_handle: int) -> None:
    child = FakeElement("Button", "Save")
    root = FakeElement("Window", "Demo", children=[child])
    root.native_window_handle = 100
    child.native_window_handle = child_handle
    resolved: list[int] = []
    raised: list[int] = []

    def root_window(handle: int) -> int:
        resolved.append(handle)
        return 100

    def foreground(handle: int) -> bool:
        raised.append(handle)
        return True

    monkeypatch.setattr(win32, "root_window", root_window)
    monkeypatch.setattr(win32, "bring_to_foreground", foreground)
    assert actions.bring_to_front(child)
    assert resolved == [child_handle or 100]
    assert raised == [100]
    assert not child.has_keyboard_focus


def test_foreground_denied_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeElement("Window", "Demo")
    monkeypatch.setattr(win32, "root_window", lambda handle: 100)
    monkeypatch.setattr(win32, "bring_to_foreground", lambda handle: False)
    assert not actions.bring_to_front(root)


def test_no_native_window_does_not_activate_another_app(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeElement("Pane", "Desktop")
    root.native_window_handle = 0

    def unexpected(handle: int) -> bool:
        pytest.fail("must not activate a window without a native handle")

    monkeypatch.setattr(win32, "bring_to_foreground", unexpected)
    assert not actions.bring_to_front(root)


def test_bound_highlight_reads_bounds_after_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    target = FakeElement("Button", "Save", rect=None)
    restored = Rect(8, 9, 40, 16)
    calls: list[str] = []

    def foreground(element: Any) -> bool:
        assert element is target
        target.rect = restored
        calls.append("foreground")
        return True

    def flash(rect: Rect, duration: int, *, color: int, block: bool) -> None:
        assert rect == restored
        assert duration == 250
        assert block
        calls.append("highlight")

    class Stub(_BoundBase):
        def resolve(self, timeout: float | None = None) -> Any:
            return target

        def _description(self) -> str:
            return "Main.save"

    monkeypatch.setattr(actions, "bring_to_front", foreground)
    monkeypatch.setattr(overlay, "flash", flash)
    Stub().highlight(250)
    assert calls == ["foreground", "highlight"]


def test_bound_highlight_without_bounds_does_not_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    target = FakeElement("Button", "Save", rect=None)

    class Stub(_BoundBase):
        def resolve(self, timeout: float | None = None) -> Any:
            return target

        def _description(self) -> str:
            return "Main.save"

    monkeypatch.setattr(actions, "bring_to_front", lambda element: False)
    monkeypatch.setattr(overlay, "flash", lambda *args, **kwargs: pytest.fail("must not flash"))
    with pytest.raises(ActionError, match="no on-screen rectangle"):
        Stub().highlight()


def test_raise_without_activating_raises_the_owning_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = FakeElement("Button", "Save")
    root = FakeElement("Window", "Demo", children=[child])
    root.native_window_handle = 100
    raised: list[int] = []
    monkeypatch.setattr(win32, "root_window", lambda handle: 100)
    monkeypatch.setattr(win32, "raise_window", lambda handle: raised.append(handle) or True)
    monkeypatch.setattr(
        win32, "bring_to_foreground", lambda handle: pytest.fail("must not take focus")
    )
    assert actions.raise_without_activating(child)
    assert raised == [100]


def test_raise_without_activating_ignores_an_element_without_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = FakeElement("Pane", "Desktop")
    pane.native_window_handle = 0
    monkeypatch.setattr(win32, "raise_window", lambda handle: pytest.fail("no window to raise"))
    assert not actions.raise_without_activating(pane)


class _Z:
    """Records the window calls made by ``win32.raise_window``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, iconic: bool, topmost: bool) -> None:
        self.calls: list[tuple[str, int]] = []
        monkeypatch.setattr(win32, "IsIconic", lambda handle: iconic)
        monkeypatch.setattr(
            win32,
            "ShowWindow",
            lambda handle, command: self.calls.append(("show", command)) or True,
        )
        monkeypatch.setattr(
            win32, "GetWindowLongW", lambda handle, index: win32.WS_EX_TOPMOST if topmost else 0
        )
        monkeypatch.setattr(
            win32,
            "SetWindowPos",
            lambda handle, after, x, y, w, h, flags: (
                self.calls.append(("pos", after, flags)) or True
            ),
        )


_NO_FOCUS = win32.SWP_NOMOVE | win32.SWP_NOSIZE | win32.SWP_NOACTIVATE


def test_raise_window_goes_topmost_then_back_without_activating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    z = _Z(monkeypatch, iconic=False, topmost=False)
    assert win32.raise_window(100)
    assert z.calls == [
        ("pos", win32.HWND_TOPMOST, _NO_FOCUS),
        ("pos", win32.HWND_NOTOPMOST, _NO_FOCUS),
    ]


def test_raise_window_keeps_a_window_that_was_already_topmost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    z = _Z(monkeypatch, iconic=False, topmost=True)
    assert win32.raise_window(100)
    assert z.calls == [("pos", win32.HWND_TOPMOST, _NO_FOCUS)]


def test_raise_window_restores_a_minimized_window_without_activating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    z = _Z(monkeypatch, iconic=True, topmost=False)
    assert win32.raise_window(100)
    assert z.calls[0] == ("show", win32.SW_SHOWNOACTIVATE)


def test_flash_runs_after_when_the_outline_is_done(monkeypatch: pytest.MonkeyPatch) -> None:
    done: list[str] = []
    monkeypatch.setattr(overlay.time, "sleep", lambda seconds: None)

    class Shown:
        def __enter__(self) -> "Shown":
            return self

        def __exit__(self, *exc: object) -> None:
            done.append("hidden")

        def show(self, rect: Rect) -> None:
            done.append("show")

        def hide(self) -> None:
            done.append("hide")

    monkeypatch.setattr(overlay, "Overlay", lambda color, thickness: Shown())
    overlay.flash(Rect(0, 0, 5, 5), 60, block=True, after=lambda: done.append("after"))
    assert done[-2:] == ["hidden", "after"]
