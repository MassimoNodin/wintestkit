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

    def flash(rect: Rect, duration: int, *, block: bool) -> None:
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


EDITOR = 500
TARGET = 100


class _Windows:
    """A scripted desktop: which window is in front, which exist, which are minimized."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, front: int) -> None:
        self.front = front
        self.alive = {EDITOR, TARGET}
        self.minimized: set[int] = set()
        self.activated: list[int] = []
        monkeypatch.setattr(win32, "root_window", lambda handle: TARGET)
        monkeypatch.setattr(win32, "GetForegroundWindow", lambda: self.front)
        monkeypatch.setattr(win32, "IsWindow", lambda handle: handle in self.alive)
        monkeypatch.setattr(win32, "IsWindowVisible", lambda handle: handle in self.alive)
        monkeypatch.setattr(win32, "IsIconic", lambda handle: handle in self.minimized)
        monkeypatch.setattr(win32, "bring_to_foreground", self.bring_to_foreground)

    def bring_to_foreground(self, handle: int) -> bool:
        self.front = handle
        self.activated.append(handle)
        return True


def _target() -> FakeElement:
    target = FakeElement("Button", "Save")
    target.native_window_handle = TARGET
    return target


def test_restore_returns_the_foreground_to_the_window_that_had_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _Windows(monkeypatch, front=EDITOR)
    restore = actions.raise_with_restore(_target())
    assert desktop.activated == [TARGET]
    restore()
    assert desktop.activated == [TARGET, EDITOR]


@pytest.mark.parametrize("change", ["user_switched", "editor_closed", "editor_minimized"])
def test_restore_leaves_the_desktop_alone_when_it_changed(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    desktop = _Windows(monkeypatch, front=EDITOR)
    restore = actions.raise_with_restore(_target())
    if change == "user_switched":
        desktop.front = 777
    elif change == "editor_closed":
        desktop.alive.discard(EDITOR)
    else:
        desktop.minimized.add(EDITOR)
    restore()
    assert desktop.activated == [TARGET]


def test_restore_does_nothing_when_the_target_was_already_in_front(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _Windows(monkeypatch, front=TARGET)
    actions.raise_with_restore(_target())()
    assert desktop.activated == [TARGET]


def test_restore_does_nothing_when_the_window_could_not_be_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _Windows(monkeypatch, front=EDITOR)
    monkeypatch.setattr(win32, "bring_to_foreground", lambda handle: False)
    actions.raise_with_restore(_target())()
    assert desktop.activated == []


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
